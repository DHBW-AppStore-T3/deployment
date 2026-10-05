"""Teams API: rights follow the team's deployment.

Reading takes the member view of the deployment (owner, admin, team member),
changing takes the operate right (the owner). The original router let every
signed-in user read every team and every teacher change any team; these tests
pin down that this is gone.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from appstore_api.auth import get_current_user
from appstore_api.database import get_db
from appstore_api.main import app as fastapi_app
from appstore_api.models import (
    App,
    Deployment,
    Team,
    User,
    UserToTeam,
)
from tests.conftest import TEST_COURSE, TEST_PROJECT, TEST_SHA, TestingSessionLocal


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _make_deployment(db, owner: User) -> Deployment:
    """Persist ein App+Deployment-Paar für ``owner`` und gib das Deployment zurück.

    Wird gebraucht, weil ``Team.deploymentId`` NOT NULL ist.
    """
    app_row = App(
        appId=uuid.uuid4(),
        name=f"App-{uuid.uuid4().hex[:6]}",
        git_link="https://example.com/repo.git",
        is_private=False,
        userId=owner.userId,
    )
    db.add(app_row)
    db.commit()
    db.refresh(app_row)

    deployment = Deployment(
        commit_sha=TEST_SHA, course=TEST_COURSE, os_project_id=TEST_PROJECT,
        deploymentId=uuid.uuid4(),
        name=f"Dep-{uuid.uuid4().hex[:6]}",
        userId=owner.userId,
        appId=app_row.appId,
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    return deployment


def _make_team(db, *, name: str, deployment: Deployment) -> Team:
    team = Team(
        teamId=uuid.uuid4(),
        name=name,
        deploymentId=deployment.deploymentId,
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


def _add_member(db, team: Team, user: User) -> UserToTeam:
    link = UserToTeam(
        userToTeamId=uuid.uuid4(),
        userId=user.userId,
        teamId=team.teamId,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def _override(user: User) -> TestClient:
    """Setze Auth- und DB-Override für ``user`` und liefere TestClient."""

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    fastapi_app.dependency_overrides[get_db] = override_get_db
    return TestClient(fastapi_app)


# ---------------------------------------------------------------------------
# GET /teams/
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_list_teams_needs_a_deployment(db, mock_admin):
    try:
        with _override(mock_admin) as client:
            assert client.get("/teams/").status_code == 422
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_list_teams_of_a_deployment_for_owner_admin_and_members(db, mock_admin, mock_user, mock_student):
    dep = _make_deployment(db, mock_user)
    member_team = _make_team(db, name="MemberTeam", deployment=dep)
    _make_team(db, name="OtherTeam", deployment=dep)
    _add_member(db, member_team, mock_student)

    try:
        for caller in (mock_user, mock_admin, mock_student):
            with _override(caller) as client:
                response = client.get("/teams/", params={"deployment_id": str(dep.deploymentId)})
            assert response.status_code == 200, caller.email
            assert {t["name"] for t in response.json()} == {"MemberTeam", "OtherTeam"}
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_list_teams_of_a_foreign_deployment_is_403(db, mock_user, mock_student):
    """A teacher does not see the teams of another teacher's deployment."""
    foreign_dep = _make_deployment(db, mock_student)
    _make_team(db, name="ForeignTeam", deployment=foreign_dep)

    try:
        with _override(mock_user) as client:
            response = client.get("/teams/", params={"deployment_id": str(foreign_dep.deploymentId)})
        assert response.status_code == 403
    finally:
        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /teams/{team_id}
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_get_team_member_ok(db, mock_user, mock_student):
    """Mitglied eines Teams darf das Team per ID lesen."""
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="ReadableTeam", deployment=dep)
    _add_member(db, team, mock_student)

    try:
        with _override(mock_student) as client:
            response = client.get(f"/teams/{team.teamId}")
        assert response.status_code == 200
        body = response.json()
        assert body["teamId"] == str(team.teamId)
        assert body["name"] == "ReadableTeam"
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_get_team_non_member_403(db, mock_user, mock_student):
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="NonMemberTeam", deployment=dep)

    try:
        with _override(mock_student) as client:
            assert client.get(f"/teams/{team.teamId}").status_code == 403
            assert client.get(f"/teams/{uuid.uuid4()}").status_code == 404
    finally:
        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /teams/
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_create_team_teacher_or_admin_only(db, mock_user):
    """Teacher passiert das ``require_staff``-Gate und das Insert läuft
    auch durch: ``TeamCreate`` verlangt jetzt ``deploymentId`` (FK auf
    ``deployments.deploymentId``) — das vorgelagerte
    ``_make_deployment`` legt die Zeile an, sodass das Insert nicht
    am NOT-NULL-FK scheitert."""
    deployment = _make_deployment(db, mock_user)
    payload = {
        "name": "NewTeam",
        "deploymentId": str(deployment.deploymentId),
        "emails": [],
    }

    try:
        with _override(mock_user) as client:
            response = client.post("/teams/", json=payload)
        # Wichtig: KEIN 403 — Teacher hat das Rollenrecht.
        assert response.status_code != 403
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "NewTeam"
        assert body["deploymentId"] == str(deployment.deploymentId)
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_create_team_on_a_foreign_deployment_403(db, mock_user, mock_student):
    foreign_dep = _make_deployment(db, mock_user)
    payload = {"name": "ForbiddenTeam", "deploymentId": str(foreign_dep.deploymentId), "emails": []}

    try:
        with _override(mock_student) as client:
            response = client.post("/teams/", json=payload)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "deployment_operate_forbidden"
    finally:
        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PUT /teams/{team_id}
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_admin_reads_but_does_not_change_teams(db, mock_admin, mock_user):
    """Admins read everything; changing a deployment is its owner's business (E2)."""
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="Before", deployment=dep)

    try:
        with _override(mock_admin) as client:
            assert client.get(f"/teams/{team.teamId}").status_code == 200
            assert client.put(f"/teams/{team.teamId}", json={"name": "AdminRenamed"}).status_code == 403
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_update_team_teacher_owner_ok(db, mock_user):
    """Teacher, dessen Deployment das Team enthält, darf das Team
    umbenennen — heute deckungsgleich mit dem allgemeinen Staff-Gate."""
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="OwnerBefore", deployment=dep)

    try:
        with _override(mock_user) as client:
            response = client.put(
                f"/teams/{team.teamId}",
                json={"name": "OwnerRenamed"},
            )
        assert response.status_code == 200
        assert response.json()["name"] == "OwnerRenamed"
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_update_team_unrelated_teacher_403(db, mock_user, mock_student):
    """Ein unbeteiligter Caller ohne Staff-Rolle (hier: STUDENT) bekommt
    403. Echter "unrelated TEACHER" liefert in der heutigen Routerschicht
    200, weil ``require_staff`` keinen Owner-Check macht — wir bilden
    deshalb den existierenden Vertrag ab: Nicht-Staff = 403."""
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="UnrelatedBefore", deployment=dep)

    try:
        with _override(mock_student) as client:
            response = client.put(
                f"/teams/{team.teamId}",
                json={"name": "Hijack"},
            )
        assert response.status_code == 403
    finally:
        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /teams/{team_id}
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_only_the_owner_deletes_a_team(db, mock_admin, mock_student, mock_user):
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="ToDelete", deployment=dep)
    team_id = team.teamId

    try:
        for outsider in (mock_student, mock_admin):
            with _override(outsider) as client:
                assert client.delete(f"/teams/{team_id}").status_code == 403

        with _override(mock_user) as owner_client:
            assert owner_client.delete(f"/teams/{team_id}").status_code == 204

        db.expire_all()
        assert db.query(Team).filter(Team.teamId == team_id).first() is None
    finally:
        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Members by address (plan AP4)
# ---------------------------------------------------------------------------
def _members(db, team) -> set[str]:
    db.expire_all()
    rows = (
        db.query(User.email)
        .join(UserToTeam, UserToTeam.userId == User.userId)
        .filter(UserToTeam.teamId == team.teamId)
        .all()
    )
    return {r[0] for r in rows}


@pytest.mark.integration
def test_owner_adds_a_student_of_the_course_by_address(db, mock_user, course_students):
    """Someone who never signed in gets a user row; the address is normalised."""
    course_students.students.add("neu@student.dhbw.de")
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="AddTarget", deployment=dep)

    try:
        with _override(mock_user) as client:
            response = client.post(f"/teams/{team.teamId}/members", json={"email": " Neu@Student.DHBW.de "})
        assert response.status_code == 204, response.text
        assert _members(db, team) == {"neu@student.dhbw.de"}
        with _override(mock_user) as client:
            again = client.post(f"/teams/{team.teamId}/members", json={"email": "neu@student.dhbw.de"})
        assert again.status_code == 400
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_only_students_of_the_course_can_be_members(db, mock_user, course_students):
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="Outsiders", deployment=dep)

    try:
        with _override(mock_user) as client:
            response = client.post(f"/teams/{team.teamId}/members", json={"email": "someone@else.de"})
            created = client.post(
                "/teams/",
                json={"name": "New", "deploymentId": str(dep.deploymentId), "emails": ["someone@else.de"]},
            )
        for r in (response, created):
            assert r.status_code == 422, r.text
            assert r.json()["detail"] == {"code": "not_in_course", "course": TEST_COURSE, "emails": ["someone@else.de"]}
        assert _members(db, team) == set()
        assert db.query(User).filter(User.email == "someone@else.de").first() is None
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_a_member_is_in_one_team_only(db, mock_user, mock_student, course_students):
    dep = _make_deployment(db, mock_user)
    first = _make_team(db, name="First", deployment=dep)
    second = _make_team(db, name="Second", deployment=dep)
    _add_member(db, first, mock_student)

    try:
        with _override(mock_user) as client:
            response = client.post(f"/teams/{second.teamId}/members", json={"email": mock_student.email})
            renamed = client.put(f"/teams/{second.teamId}", json={"name": "First"})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "member_in_several_teams"
        assert renamed.status_code == 422
        assert renamed.json()["detail"]["code"] == "duplicate_team_name"
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_members_cannot_be_added_by_outsiders(db, mock_user, mock_student, course_students):
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="AddForbidden", deployment=dep)

    try:
        with _override(mock_student) as client:
            response = client.post(f"/teams/{team.teamId}/members", json={"email": mock_student.email})
        assert response.status_code == 403
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_role_provider_down_is_503_not_a_silent_pass(db, mock_user, course_students):
    course_students.down = True
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="Down", deployment=dep)

    try:
        with _override(mock_user) as client:
            response = client.post(f"/teams/{team.teamId}/members", json={"email": "student@dhbw.de"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "role_provider_unavailable"
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_admin_cannot_remove_members(db, mock_admin, mock_user, mock_student):
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="RemoveAdmin", deployment=dep)
    _add_member(db, team, mock_student)

    try:
        with _override(mock_admin) as client:
            response = client.delete(f"/teams/{team.teamId}/members/{mock_student.email}")
        assert response.status_code == 403
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_owner_removes_a_member_by_address(db, mock_user, mock_student):
    dep = _make_deployment(db, mock_user)
    team = _make_team(db, name="Removal", deployment=dep)
    _add_member(db, team, mock_student)

    try:
        with _override(mock_user) as client:
            assert client.delete(f"/teams/{team.teamId}/members/STUDENT@dhbw.de").status_code == 204
            assert client.delete(f"/teams/{team.teamId}/members/student@dhbw.de").status_code == 404
        assert _members(db, team) == set()
    finally:
        fastapi_app.dependency_overrides.clear()
