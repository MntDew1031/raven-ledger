import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserProfile
from app.schemas import ProfileResponse, UserResponse


async def ensure_profile(db: AsyncSession, user: User) -> UserProfile:
    loaded_profile = user.__dict__.get("profile")
    if loaded_profile is not None:
        return loaded_profile
    existing_profile = await db.get(UserProfile, user.id)
    if existing_profile is not None:
        user.profile = existing_profile
        return existing_profile
    profile = UserProfile(user_id=user.id)
    db.add(profile)
    await db.flush()
    user.profile = profile
    return profile


def avatar_url(user_id: uuid.UUID, profile: UserProfile) -> str | None:
    if not profile.avatar_mime or not profile.avatar_revision:
        return None
    return f"/api/v1/profile/avatar/{user_id}?v={profile.avatar_revision}"


def user_response(user: User, profile: UserProfile) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=avatar_url(user.id, profile),
        theme=profile.theme,
        accent=profile.accent,
        density=profile.density,
        button_style=profile.button_style,
        start_page=profile.start_page,
        mfa_enabled=bool(user.mfa_enabled_at),
    )


def profile_response(user: User, profile: UserProfile) -> ProfileResponse:
    return ProfileResponse(
        **user_response(user, profile).model_dump(),
        avatar_size=profile.avatar_size,
    )
