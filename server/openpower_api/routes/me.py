from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthenticatedUser, get_current_user
from ..db import Profile, get_session
from ..schemas import ProfileOut

router = APIRouter(tags=["me"])


@router.get("/me", response_model=ProfileOut)
async def get_me(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProfileOut:
    result = await session.execute(select(Profile).where(Profile.id == user.id))
    profile = result.scalar_one_or_none()
    if profile is None:
        # Normally created by the `handle_new_user` trigger on auth.users insert
        # (see schema.sql). Defensive fallback in case this request races that
        # trigger, or runs against a test database with no trigger at all.
        profile = Profile(id=user.id)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)

    return ProfileOut(
        id=profile.id,
        display_name=profile.display_name,
        email=user.email,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
