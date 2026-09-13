"""Authentication service: Argon2id password hashing and session management."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import UserStatus
from app.models.identity import User
from app.models.session import Session

_ph = PasswordHasher(type=Type.ID)
_DUMMY_PASSWORD_HASH = _ph.hash("DocGrading dummy authentication hash")


def _email_lock_id(email: str) -> int:
    digest = hashlib.sha256(email.encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def csrf_token_for_session(session_id: uuid.UUID) -> str:
    """Derive a readable CSRF token from an opaque 122-bit session secret."""
    return hashlib.sha256(session_id.bytes).hexdigest()


def auth_cookie_names(secure: bool) -> tuple[str, str]:
    """Use browser-enforced host-only cookie names whenever HTTPS is active."""
    prefix = "__Host-" if secure else ""
    return f"{prefix}session_id", f"{prefix}csrf_token"


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
    """Validate credentials and enforce a persistent fixed-window lockout."""
    settings = get_settings()
    normalized_email = email.strip().lower()
    await db.execute(
        select(func.pg_advisory_xact_lock(_email_lock_id(normalized_email)))
    )
    now = datetime.now(UTC)
    user = (
        await db.execute(
            select(User)
            .where(
                func.lower(User.email) == normalized_email,
                User.status == UserStatus.ACTIVE,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None

    changed = False
    if user.login_locked_until is not None:
        if user.login_locked_until > now:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            return None
        user.failed_login_attempts = 0
        user.failed_login_window_started_at = None
        user.login_locked_until = None
        changed = True

    if not verify_password(password, user.password_hash):
        window = timedelta(seconds=settings.login_failure_window_seconds)
        if (
            user.failed_login_window_started_at is None
            or user.failed_login_window_started_at + window <= now
        ):
            user.failed_login_attempts = 1
            user.failed_login_window_started_at = now
        else:
            user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.login_max_failed_attempts:
            user.login_locked_until = now + timedelta(
                seconds=settings.login_lockout_seconds
            )
        await db.flush()
        return None

    if user.failed_login_attempts or user.failed_login_window_started_at is not None:
        user.failed_login_attempts = 0
        user.failed_login_window_started_at = None
        changed = True
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        changed = True
    if changed:
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
    stmt = (
        select(Session)
        .join(Session.user)
        .where(
            Session.id == session_id,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
            User.status == UserStatus.ACTIVE,
        )
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
