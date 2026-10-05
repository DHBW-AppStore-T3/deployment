"""Teams of a deployment.

A team belongs to exactly one deployment, and so do the rights on it: whoever
may see the deployment (member view) may see its teams, whoever may operate
it may change them. The original let every signed-in user list every team
with its members, and every teacher change any team.

Members are given by address and must be students of the deployment's
course, each in one team only (plan AP4); the same check runs when a
deployment is created. Changing a team does not change infrastructure that is
already deployed: that follows on the next deploy.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from appstore_api.auth import get_current_user
from appstore_api.crud import deployments as crud_deployments
from appstore_api.crud import teams as crud_teams
from appstore_api.crud import users as crud_users
from appstore_api.database import get_db
from appstore_api.models import Deployment, User
from appstore_api.schemas import (
    MemberEmail,
    TeamCreate,
    TeamMemberAdd,
    TeamResponse,
    TeamUpdate,
    TeamWithMembers,
)
from appstore_api.services import courses
from appstore_api.utils.capabilities import (
    ensure_operate_deployment,
    ensure_view_deployment_member,
)

router = APIRouter()


def _deployment(db: Session, deployment_id: UUID) -> Deployment:
    """Load a deployment or raise 404."""
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    return deployment


def _team_and_deployment(db: Session, team_id: UUID):
    """Load a team and its deployment, the object the rights are checked on; 404 if either is missing."""
    team = crud_teams.get_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team, _deployment(db, team.deploymentId)


def _check_rosters(db: Session, deployment: Deployment, change) -> None:
    """Run the course check on the deployment's teams as they would be after ``change``.

    ``change`` maps the current ``[(name, emails)]`` (keyed by team id) to
    the new one, so duplicate names and members are judged across all teams.
    Raises 422 (from ``courses.ensure_team_members``) when the result breaks
    a rule, 503 when the role provider cannot list the students.
    """
    rosters = {team.teamId: (team.name, emails) for team, emails in crud_teams.get_rosters(db, deployment.deploymentId)}
    courses.ensure_team_members(deployment.course, list(change(rosters).values()))


# ----------------------------------------------------------------
# GET TEAMS OF A DEPLOYMENT
# ----------------------------------------------------------------
@router.get("/", response_model=list[TeamResponse])
def list_teams(
    deployment_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the teams of one deployment, paged with ``skip``/``limit``.

    Requires the member view of the deployment (owner, project peers,
    admins, team members); 403 otherwise, 404 if the deployment does not
    exist.
    """
    ensure_view_deployment_member(current_user, _deployment(db, deployment_id), db)
    return crud_teams.get_teams(db, skip=skip, limit=limit, deployment_id=deployment_id)


# ----------------------------------------------------------------
# GET TEAM BY ID
# ----------------------------------------------------------------
@router.get("/{team_id}", response_model=TeamWithMembers)
def get_team(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a team with its members.

    Requires the member view of the team's deployment (403 otherwise);
    404 if the team does not exist.
    """
    team, deployment = _team_and_deployment(db, team_id)
    ensure_view_deployment_member(current_user, deployment, db)
    return team


# ----------------------------------------------------------------
# CREATE TEAM
# ----------------------------------------------------------------
@router.post("/", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    team: TeamCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a team with its members to a deployment the caller operates.

    Owner or project peer of the deployment only (403 otherwise; admins
    cannot). Members are given by address and must be students of the
    deployment's course and in no other team of it; team names must be
    unique (422 otherwise). Unknown addresses get a user row created.
    404 if the deployment does not exist, 503 if the role provider cannot
    list the course's students.
    """
    deployment = _deployment(db, team.deploymentId)
    ensure_operate_deployment(current_user, deployment, db)
    _check_rosters(db, deployment, lambda r: {**r, None: (team.name, team.emails)})
    users = crud_users.ensure_users(db, team.emails)
    return crud_teams.create_team(db, team, [users[e].userId for e in team.emails])


# ----------------------------------------------------------------
# UPDATE TEAM
# ----------------------------------------------------------------
@router.put("/{team_id}", response_model=TeamResponse)
def update_team(
    team_id: UUID,
    team_update: TeamUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rename a team.

    Owner or project peer of the deployment only (403 otherwise). 404 if
    the team does not exist, 422 if the new name is taken by another team
    of the deployment.
    """
    _team, deployment = _team_and_deployment(db, team_id)
    ensure_operate_deployment(current_user, deployment, db)
    if team_update.name is not None:
        new_name = team_update.name
        _check_rosters(db, deployment, lambda r: {**r, team_id: (new_name, r[team_id][1])})
    return crud_teams.update_team(db, team_id, team_update)


# ----------------------------------------------------------------
# DELETE TEAM
# ----------------------------------------------------------------
@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a team; its infrastructure is removed on the next deploy, not now.

    Owner or project peer of the deployment only (403 otherwise). 404 if
    the team does not exist.
    """
    _team, deployment = _team_and_deployment(db, team_id)
    ensure_operate_deployment(current_user, deployment, db)
    crud_teams.delete_team(db, team_id)
    return None


# ----------------------------------------------------------------
# ADD MEMBER
# ----------------------------------------------------------------
@router.post("/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_team_member(
    team_id: UUID,
    member: TeamMemberAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a student of the deployment's course to the team, by address.

    Owner or project peer of the deployment only (403 otherwise). 400 if
    the user is already in this team, 422 if the address is not a student
    of the course or already in another team of the deployment. 404 if
    the team does not exist, 503 if the role provider cannot be reached.
    """
    _team, deployment = _team_and_deployment(db, team_id)
    ensure_operate_deployment(current_user, deployment, db)
    user = crud_users.get_user_by_email(db, member.email)
    if user is not None and crud_teams.is_member(db, team_id, user.userId):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already in team")
    _check_rosters(db, deployment, lambda r: {**r, team_id: (r[team_id][0], [*r[team_id][1], member.email])})
    user = crud_users.ensure_users(db, [member.email])[member.email]
    crud_teams.add_user_to_team(db, team_id, user.userId)
    return None


# ----------------------------------------------------------------
# REMOVE MEMBER
# ----------------------------------------------------------------
@router.delete("/{team_id}/members/{email}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(
    team_id: UUID,
    email: MemberEmail,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a member, given by address, from the team.

    Owner or project peer of the deployment only (403 otherwise). 404 if
    the team does not exist or the address is not a member of it.
    """
    _team, deployment = _team_and_deployment(db, team_id)
    ensure_operate_deployment(current_user, deployment, db)
    user = crud_users.get_user_by_email(db, email)
    if user is None or not crud_teams.remove_user_from_team(db, team_id, user.userId):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not in team")
    return None
