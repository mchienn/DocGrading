"""Authentication service: Argon2id password hashing and session management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import UserStatus
from app.models.identity import User
from app.models.session import Session

_ph = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    """Hash *password* with Argon2id and return the encoded hash string."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return ``True`` when *password* matches *password_hash*."""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def needs_rehash(password_hash: str) -> bool:
    """Return ``True`` when the hash parameters are outdated."""
    return _ph.check_needs_rehash(password_hash)


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    """Validate credentials and return the active user, or ``None``."""
    stmt = select(User).where(
        User.email == email,
        User.status == UserStatus.ACTIVE,
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        await db.flush()
    return user


async def create_session(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> Session:
    """Create a new server-side session and return it (unflushed)."""
    settings = get_settings()
    now = datetime.now(UTC)
    session = Session(
        id=uuid.uuid4(),
        user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_lifetime_seconds),
    )
    db.add(session)
    await db.flush()
    return session


async def get_valid_session(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> Session | None:
    """Load a non-expired, non-revoked session with its user eagerly joined."""
    stmt = select(Session).where(
        Session.id == session_id,
        Session.revoked_at.is_(None),
        Session.expires_at > datetime.now(UTC),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def revoke_session(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> None:
    """Mark a session as revoked."""
    session = await db.get(Session, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.flush()
