from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models.setting import AppSetting

router = APIRouter(prefix="/api/settings", tags=["settings"])

MASKED_PLACEHOLDER = "••••••••"


def _mask_key(value: str) -> str:
    """Show only the last 4 characters of the key."""
    if not value or len(value) < 8:
        return MASKED_PLACEHOLDER
    return f"sk-ant-...{value[-4:]}"


class SettingsResponse(BaseModel):
    anthropic_api_key_set: bool
    anthropic_api_key_masked: Optional[str]
    anthropic_api_key_source: str  # "env", "database", or "none"


class SaveKeyRequest(BaseModel):
    anthropic_api_key: str


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    import os
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return SettingsResponse(
            anthropic_api_key_set=True,
            anthropic_api_key_masked=_mask_key(env_key),
            anthropic_api_key_source="env",
        )

    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "anthropic_api_key")
    )
    setting = result.scalar_one_or_none()
    if setting and setting.value:
        return SettingsResponse(
            anthropic_api_key_set=True,
            anthropic_api_key_masked=_mask_key(setting.value),
            anthropic_api_key_source="database",
        )

    return SettingsResponse(
        anthropic_api_key_set=False,
        anthropic_api_key_masked=None,
        anthropic_api_key_source="none",
    )


@router.post("")
async def save_settings(payload: SaveKeyRequest, db: AsyncSession = Depends(get_db)):
    key = payload.anthropic_api_key.strip()

    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "anthropic_api_key")
    )
    setting = result.scalar_one_or_none()

    if not key:
        # Clear the key
        if setting:
            await db.delete(setting)
        await db.commit()
        return {"status": "cleared"}

    if setting:
        setting.value = key
        setting.updated_at = datetime.utcnow()
    else:
        db.add(AppSetting(key="anthropic_api_key", value=key))

    await db.commit()
    return {"status": "saved", "masked": _mask_key(key)}
