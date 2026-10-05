"""Courses, teams by address and "Meine Zugänge" (plan AP4, E5)."""

from __future__ import annotations

import uuid

import pytest

from appstore_api.models import Deployment, Task, TaskStatus, TaskType, Team, User, UserToTeam
from appstore_api.utils.crypto import cipher
from appstore_shared.jobs import seal_outputs
from tests.conftest import (
    TEST_COURSE,
    TEST_PROJECT,
    TEST_SHA,
    add_credential,
    approve_version,
    create_app_in_db,
    queued_task,
)

pytestmark = pytest.mark.integration

OTHER_COURSE = "group:wwi24abc"


# ----------------------------------------------------------------
# /me
# ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("client", {"is_admin": False, "is_dozent": True, "can_register_apps": True, "can_deploy": True}),
        ("student_client", {"is_admin": False, "is_dozent": False, "can_register_apps": False, "can_deploy": False}),
        ("admin_client", {"is_admin": True, "is_dozent": False, "can_register_apps": True, "can_deploy": False}),
    ],
)
def test_me_says_what_to_offer(request, fixture, expected):
    body = request.getfixturevalue(fixture).get("/me").json()
    assert {k: body[k] for k in expected} == expected


# ----------------------------------------------------------------
# /me/courses and /courses/{course}/students
# ----------------------------------------------------------------
def test_a_dozent_sees_the_courses_they_teach(client, course_students):
    response = client.get("/me/courses")

    assert response.status_code == 200
    assert response.json() == [{"course": TEST_COURSE, "display_name": "WWI23SEB", "description": "Kurs"}]


def test_a_course_stays_listed_when_it_cannot_be_described(client, course_students):
    course_students.down = True

    assert client.get("/me/courses").json() == [{"course": TEST_COURSE, "display_name": "wwi23seb", "description": ""}]


def test_a_student_teaches_no_course(student_client):
    assert student_client.get("/me/courses").json() == []


def test_students_of_a_taught_course(client, course_students):
    course_students.students.add("b@student.dhbw.de")

    response = client.get(f"/courses/{TEST_COURSE}/students")

    assert response.status_code == 200
    assert response.json() == ["b@student.dhbw.de", "student@dhbw.de"]


def test_students_of_other_courses_are_not_listed(client, student_client, course_students):
    other = client.get(f"/courses/{OTHER_COURSE}/students")
    assert other.status_code == 403
    assert other.json()["detail"] == {"code": "course_not_taught", "required": [f"{OTHER_COURSE}#dozent"]}

    assert student_client.get(f"/courses/{TEST_COURSE}/students").status_code == 403
    assert client.get("/courses/wwi23seb/students").status_code == 422


def test_students_while_the_role_provider_is_down(client, course_students):
    course_students.down = True

    response = client.get(f"/courses/{TEST_COURSE}/students")

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "role_provider_unavailable"}


# ----------------------------------------------------------------
# deploying for a course
# ----------------------------------------------------------------
def _deploy(client, app, *, course=TEST_COURSE, teams=()):
    return client.post(
        "/deployments/",
        json={
            "name": "d",
            "appId": str(app.appId),
            "releaseTag": "v1.0",
            "course": course,
            "credentialId": str(app.credential.credentialId),
            "teams": list(teams),
        },
    )


@pytest.fixture
def deployable(db, mock_user):
    credential = add_credential(db, mock_user)
    app = create_app_in_db(db, mock_user)
    approve_version(db, app, "v1.0")
    app.credential = credential
    return app


def test_deploy_only_for_a_course_one_teaches(client, db, deployable, course_students):
    response = _deploy(client, deployable, course=OTHER_COURSE)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "course_not_taught"
    assert db.query(Deployment).count() == 0


def test_teams_by_address(client, db, deployable, course_students):
    course_students.students |= {"a@student.dhbw.de", "b@student.dhbw.de"}

    response = _deploy(
        client,
        deployable,
        teams=[
            {"name": "Team-1", "emails": ["A@Student.dhbw.de", "student@dhbw.de"]},
            {"name": "Team-2", "emails": ["b@student.dhbw.de"]},
        ],
    )

    assert response.status_code == 201, response.text
    assert response.json()["course"] == TEST_COURSE
    deployment_id = uuid.UUID(response.json()["deploymentId"])
    _task, payload = queued_task(db, deployment_id)
    assert payload["teams"] == {
        "Team-1": [{"email": "a@student.dhbw.de"}, {"email": "student@dhbw.de"}],
        "Team-2": [{"email": "b@student.dhbw.de"}],
    }
    # People who never signed in get a row, so the team can point at them.
    members = (
        db.query(Team.name, User.email)
        .join(UserToTeam, UserToTeam.teamId == Team.teamId)
        .join(User, User.userId == UserToTeam.userId)
        .filter(Team.deploymentId == deployment_id)
        .all()
    )
    assert sorted(members) == [
        ("Team-1", "a@student.dhbw.de"),
        ("Team-1", "student@dhbw.de"),
        ("Team-2", "b@student.dhbw.de"),
    ]


@pytest.mark.parametrize(
    ("teams", "code"),
    [
        ([{"name": "T", "emails": ["stranger@example.org"]}], "not_in_course"),
        ([{"name": "T", "emails": ["student@dhbw.de"]}, {"name": "U", "emails": ["student@dhbw.de"]}], "member_in_several_teams"),
        ([{"name": "T", "emails": []}, {"name": "T", "emails": []}], "duplicate_team_name"),
    ],
)
def test_bad_teams_are_refused_before_anything_is_written(client, db, deployable, course_students, teams, code):
    response = _deploy(client, deployable, teams=teams)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code
    assert db.query(Deployment).count() == 0
    assert db.query(User).filter(User.email == "stranger@example.org").first() is None


@pytest.mark.parametrize("email", ["no-at-sign", "two words@example.org", ""])
def test_malformed_addresses_are_refused(client, deployable, course_students, email):
    assert _deploy(client, deployable, teams=[{"name": "T", "emails": [email]}]).status_code == 422


# ----------------------------------------------------------------
# /me/access
# ----------------------------------------------------------------
def test_my_access_lists_only_my_own_account(db, mock_user, mock_student, student_client):
    app = create_app_in_db(db, mock_user, name="Online-IDE")
    dep = Deployment(name="ide", appId=app.appId, userId=mock_user.userId, commit_sha=TEST_SHA, course=TEST_COURSE, os_project_id=TEST_PROJECT)
    db.add(dep)
    db.flush()
    team = Team(name="Team-1", deploymentId=dep.deploymentId)
    db.add(team)
    db.flush()
    mate = User(email="mate@dhbw.de", username="mate")
    db.add(mate)
    db.flush()
    db.add_all([UserToTeam(userId=mock_student.userId, teamId=team.teamId), UserToTeam(userId=mate.userId, teamId=team.teamId)])
    outputs = {
        "team_vms": {"value": {"Team-1": {"url": "http://10.0.0.1"}}},
        "user_accounts": {
            "value": {
                "Team-1-studentuser": {"username": "studentuser", "auth": "mine", "type": "password"},
                "Team-1-mate": {"username": "mate", "auth": "theirs", "type": "password"},
            }
        },
    }
    db.add(
        Task(
            deploymentId=dep.deploymentId,
            type=TaskType.DEPLOY,
            status=TaskStatus.SUCCESS,
            outputs=seal_outputs(cipher, outputs),
        )
    )
    db.commit()

    response = student_client.get("/me/access")

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["name"] == "ide"
    assert entry["app_name"] == "Online-IDE"
    assert entry["team_name"] == "Team-1"
    assert entry["course"] == TEST_COURSE
    assert entry["user_accounts"] == {"Team-1-studentuser": {"username": "studentuser", "auth": "mine", "type": "password"}}
    assert entry["team_vms"] == {"Team-1": {"url": "http://10.0.0.1"}}


def test_my_access_is_empty_for_someone_in_no_team(client):
    assert client.get("/me/access").json() == []
