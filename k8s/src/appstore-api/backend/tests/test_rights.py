"""The access rules of plan D3/E2/E6 through the API."""

from __future__ import annotations

import uuid

import pytest

from appstore_api.models import App, Deployment
from tests.conftest import TEST_COURSE, TEST_PROJECT, TEST_SHA, create_app_in_db

pytestmark = pytest.mark.integration


def _deployment(db, owner) -> Deployment:
    app = create_app_in_db(db, owner)
    dep = Deployment(commit_sha=TEST_SHA, course=TEST_COURSE, os_project_id=TEST_PROJECT, name=f"d-{uuid.uuid4().hex[:6]}", appId=app.appId, userId=owner.userId)
    db.add(dep)
    db.commit()
    return dep


def test_students_register_no_apps(student_client):
    response = student_client.post("/apps/", json={"name": "x", "git_link": "https://github.com/o/r"})
    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "role_required", "required": ["dozent", "admin"]}


def test_students_start_no_deployments(student_client, db, mock_student):
    app = App(name="a", userId=mock_student.userId, git_link="https://github.com/o/r", is_private=True)
    db.add(app)
    db.commit()

    response = student_client.post(
        "/deployments/", json={"name": "d", "appId": str(app.appId), "releaseTag": "v1", "course": TEST_COURSE, "credentialId": str(uuid.uuid4()), "teams": []}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "role_required", "required": ["dozent"]}


def test_a_teacher_does_not_see_another_teachers_deployment(client, db, mock_user):
    other_teacher = type(mock_user)(email="other@dhbw.de", username="other")
    db.add(other_teacher)
    db.commit()
    foreign = _deployment(db, other_teacher)
    own = _deployment(db, mock_user)

    listed = {d["deploymentId"] for d in client.get("/deployments/").json()}

    assert listed == {str(own.deploymentId)}
    assert client.get(f"/deployments/{foreign.deploymentId}").status_code == 403
    assert client.get(f"/tasks/deployment/{foreign.deploymentId}").status_code == 403


def test_admins_read_other_peoples_deployments_but_do_not_operate_them(admin_client, db, mock_user):
    dep = _deployment(db, mock_user)

    assert admin_client.get(f"/deployments/{dep.deploymentId}").status_code == 200
    assert admin_client.post(f"/deployments/{dep.deploymentId}/pause").status_code == 403




def _with_member(db, owner, member):
    from appstore_api.models import Team, UserToTeam

    dep = _deployment(db, owner)
    team = Team(name="T", deploymentId=dep.deploymentId)
    db.add(team)
    db.flush()
    db.add(UserToTeam(userId=member.userId, teamId=team.teamId))
    db.commit()
    return dep


# One client per test: the client fixtures share the app's dependency
# overrides, so two in one test would both be the last one.
def test_the_detail_tells_the_owner_what_they_may_do(client, db, mock_user, mock_student):
    dep = _with_member(db, mock_user, mock_student)
    assert client.get(f"/deployments/{dep.deploymentId}").json()["permissions"] == {"owner_view": True, "operate": True}


def test_the_detail_tells_a_member_what_they_may_do(student_client, db, mock_user, mock_student):
    dep = _with_member(db, mock_user, mock_student)
    assert student_client.get(f"/deployments/{dep.deploymentId}").json()["permissions"] == {"owner_view": False, "operate": False}
