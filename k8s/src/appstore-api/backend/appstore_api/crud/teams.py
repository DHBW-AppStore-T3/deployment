"""Database access for teams of a deployment and their members (``UserToTeam``).

Called by ``routers/teams.py`` and the deploy path in ``routers/deployments.py``;
rights and the "members must be students of the course" rule are checked there.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from appstore_api.models import Team, User, UserToTeam
from appstore_api.schemas import TeamCreate, TeamUpdate


def get_team(db: Session, team_id: UUID) -> Team | None:
    """Get team by ID."""
    return db.query(Team).filter(Team.teamId == team_id).first()


def get_teams(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    deployment_id: UUID | None = None
) -> list[Team]:
    """Get teams, optionally only those of one deployment."""
    query = db.query(Team)

    if deployment_id:
        query = query.filter(Team.deploymentId == deployment_id)

    return query.offset(skip).limit(limit).all()


def _add_team_members(db: Session, team: Team, user_ids: list[UUID]) -> None:
    """Stage ``UserToTeam`` membership rows for ``team``.

    Adds one association row per user id to the session without
    committing or flushing — the caller controls transaction
    boundaries. ``team.teamId`` must already be populated (via a prior
    commit or flush) so the foreign key can be set.
    """
    for user_id in user_ids:
        user_to_team = UserToTeam(
            userId=user_id,
            teamId=team.teamId
        )
        db.add(user_to_team)


def create_team(db: Session, team: TeamCreate, user_ids: list[UUID]) -> Team:
    """Create a new team with the given members.

    ``Team`` has a NOT NULL ``deploymentId`` FK, so the request payload
    must carry the deployment to attach to. Team and memberships are
    committed together.
    """
    db_team = Team(
        name=team.name,
        deploymentId=team.deploymentId
    )
    db.add(db_team)
    # Flush (not commit) so ``teamId`` is populated before staging the
    # memberships; a failure there leaves no team without its members.
    db.flush()

    _add_team_members(db, db_team, user_ids)

    db.commit()
    db.refresh(db_team)
    return db_team


def update_team(db: Session, team_id: UUID, team_update: TeamUpdate) -> Team | None:
    """Apply the set fields of ``team_update`` (the name) and commit; None if not found."""
    db_team = get_team(db, team_id)
    if not db_team:
        return None

    update_data = team_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_team, field, value)

    db.commit()
    db.refresh(db_team)
    return db_team


def delete_team(db: Session, team_id: UUID) -> bool:
    """Delete a team and commit; False if it does not exist."""
    db_team = get_team(db, team_id)
    if not db_team:
        return False

    db.delete(db_team)
    db.commit()
    return True


def is_member(db: Session, team_id: UUID, user_id: UUID) -> bool:
    """Whether ``user_id`` belongs to the team."""
    return (
        db.query(UserToTeam.userToTeamId)
        .filter(UserToTeam.teamId == team_id, UserToTeam.userId == user_id)
        .first()
        is not None
    )


def add_user_to_team(db: Session, team_id: UUID, user_id: UUID) -> bool:
    """Add a user to a team and commit; False if they already are a member."""
    # Check if already exists
    existing = db.query(UserToTeam).filter(
        UserToTeam.teamId == team_id,
        UserToTeam.userId == user_id
    ).first()

    if existing:
        return False

    user_to_team = UserToTeam(
        userId=user_id,
        teamId=team_id
    )
    db.add(user_to_team)
    db.commit()
    return True


def remove_user_from_team(db: Session, team_id: UUID, user_id: UUID) -> bool:
    """Remove a user from a team and commit; False if they were not a member."""
    user_to_team = db.query(UserToTeam).filter(
        UserToTeam.teamId == team_id,
        UserToTeam.userId == user_id
    ).first()

    if not user_to_team:
        return False

    db.delete(user_to_team)
    db.commit()
    return True


def create_teams_for_deployment(
    db: Session,
    deployment_id: UUID,
    teams_data: list[dict]
) -> list[Team]:
    """Stage the teams of a new deployment with their members; flushes, does not commit.

    ``teams_data``: ``[{"name": "team1", "userIds": [uuid1, uuid2]}, ...]``.
    Part of the deploy transaction, together with the deployment and its task.
    """
    created_teams = []

    for team_data in teams_data:
        # Create team
        db_team = Team(
            name=team_data["name"],
            deploymentId=deployment_id
        )
        db.add(db_team)
        db.flush()  # Get team ID

        _add_team_members(db, db_team, team_data.get("userIds", []))

        created_teams.append(db_team)

    return created_teams


def get_rosters(db: Session, deployment_id: UUID) -> list[tuple[Team, list[str]]]:
    """Each team of the deployment with its members' addresses."""
    teams = db.query(Team).filter(Team.deploymentId == deployment_id).all()
    rows = (
        db.query(UserToTeam.teamId, User.email)
        .join(User, User.userId == UserToTeam.userId)
        .join(Team, Team.teamId == UserToTeam.teamId)
        .filter(Team.deploymentId == deployment_id)
        .all()
    )
    emails: dict[UUID, list[str]] = {}
    for team_id, email in rows:
        emails.setdefault(team_id, []).append(email)
    return [(t, sorted(emails.get(t.teamId, []))) for t in teams]
