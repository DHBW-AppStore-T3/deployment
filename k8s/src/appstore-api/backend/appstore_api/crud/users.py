"""Database access for ``users`` rows, which only give people an id to reference.

Rows are never updated here; see the comment below.
"""

from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from appstore_api.models import User
from appstore_shared.models import utcnow

# A row is created on first sign-in (``auth.get_current_user``) or when someone
# is put into a team before they ever signed in (``ensure_users``). Nothing
# here changes a row: profile and rights belong to the identity provider and
# role-provider-service.


def get_user(db: Session, user_id: UUID) -> User | None:
    """Get user by ID."""
    return db.query(User).filter(User.userId == user_id).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    """Get user by e-mail address (expected lower-case, as stored)."""
    return db.query(User).filter(User.email == email).first()


def ensure_users(db: Session, emails: list[str]) -> dict[str, User]:
    """The rows for ``emails`` (already normalised), creating missing ones.

    Does not commit: teams are built in the deploy transaction. ``ON
    CONFLICT DO NOTHING`` keeps a concurrent first sign-in of the same
    person from failing the deploy.
    """
    if not emails:
        return {}
    db.execute(
        insert(User)
        .values([
            {"userId": uuid4(), "email": e, "username": e.split("@", 1)[0], "created_at": utcnow()}
            for e in emails
        ])
        .on_conflict_do_nothing(index_elements=[User.email])
    )
    rows = db.query(User).filter(User.email.in_(emails)).all()
    return {u.email: u for u in rows}
