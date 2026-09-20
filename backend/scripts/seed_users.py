"""Seed initial development users (admin, teacher, student)."""

from __future__ import annotations

import asyncio
import uuid

import sqlalchemy as sa

from app.db.session import _session_factory
from app.models.enums import UserRole, UserStatus
from app.models.identity import User
from app.services.auth import hash_password

USERS = [
    {
        "email": "admin@docgrading.com",
        "display_name": "Admin",
        "roles": [UserRole.ADMIN],
        "password": "Password123!",
    },
    {
        "email": "teacher@docgrading.com",
        "display_name": "Teacher",
        "roles": [UserRole.TEACHER],
        "password": "Password123!",
    },
    {
        "email": "student@docgrading.com",
        "display_name": "Student",
        "roles": [UserRole.STUDENT],
        "password": "Password123!",
    },
]


async def seed_users() -> None:
    session_factory = _session_factory()
    async with session_factory() as session:
        for user_data in USERS:
            email = user_data["email"].lower()
            stmt = sa.select(User).where(sa.func.lower(User.email) == email)
            existing = (await session.execute(stmt)).scalar_one_or_none()

            pwd_hash = await asyncio.to_thread(hash_password, user_data["password"])

            if existing:
                existing.display_name = user_data["display_name"]
                existing.roles = user_data["roles"]
                existing.password_hash = pwd_hash
                existing.status = UserStatus.ACTIVE
                existing.failed_login_attempts = 0
                existing.login_locked_until = None
                print(f"Updated user: {email}")
            else:
                new_user = User(
                    id=uuid.uuid4(),
                    email=email,
                    display_name=user_data["display_name"],
                    password_hash=pwd_hash,
                    roles=user_data["roles"],
                    status=UserStatus.ACTIVE,
                    revision=1,
                )
                session.add(new_user)
                print(f"Created user: {email}")

        await session.commit()
    print("Seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed_users())
