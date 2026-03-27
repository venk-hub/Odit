from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import asyncio
import os

from app.database import get_db
from app.models.setting import AppSetting

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


async def _resolve_api_key(db: AsyncSession) -> str:
    """Return the Anthropic API key from env or DB, empty string if not found."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    try:
        result = await db.execute(
            select(AppSetting).where(AppSetting.key == "anthropic_api_key")
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            return setting.value.strip()
    except Exception:
        pass
    return ""


class VendorSuggestionRequest(BaseModel):
    url: str


@router.post("/vendors")
async def suggest_vendors(
    payload: VendorSuggestionRequest,
    db: AsyncSession = Depends(get_db),
):
    """AI-powered vendor suggestion based on website URL."""
    if not payload.url or not payload.url.startswith("http"):
        return {"vendors": []}

    api_key = await _resolve_api_key(db)
    if not api_key:
        return {"vendors": []}

    # Temporarily set the key so _get_client() picks it up
    os.environ["ANTHROPIC_API_KEY"] = api_key

    try:
        from app.ai.claude_client import suggest_vendors_for_url
        vendors = await asyncio.to_thread(suggest_vendors_for_url, payload.url)
        return {"vendors": vendors}
    except Exception:
        return {"vendors": []}
