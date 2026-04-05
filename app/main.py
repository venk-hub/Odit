from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
import asyncio
import json
import logging
import os
import posixpath

from app.config import get_settings
from app.api import audits, pages, issues, vendors, exports, comparisons, suggestions, events, help as help_api
from app.api import settings as settings_api
from app.web import routes as web_routes

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("odit.app")


async def _scheduler_loop():
    """Background task: fire scheduled audits when they come due (checks every 60s)."""
    from app.database import AsyncSessionLocal
    from app.models.scheduled_audit import ScheduledAudit
    from app.models.audit import AuditConfig, AuditRun, AuditStatus
    from sqlalchemy import select
    from datetime import datetime, timedelta
    from urllib.parse import urlparse

    while True:
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.utcnow()
                result = await db.execute(
                    select(ScheduledAudit)
                    .where(ScheduledAudit.is_active == True)
                    .where(ScheduledAudit.next_run_at <= now)
                )
                due = result.scalars().all()
                for sched in due:
                    try:
                        parsed = urlparse(sched.url)
                        config = AuditConfig(
                            base_url=sched.url,
                            mode=sched.mode,
                            max_pages=sched.max_pages,
                            max_depth=3,
                            allowed_domains=[parsed.netloc],
                            device_type="desktop",
                            consent_behavior="no_interaction",
                            expected_vendors=[],
                            include_patterns=[],
                            exclude_patterns=[],
                            seed_urls=[],
                            journey_instructions=[],
                            auth_cookies=sched.auth_cookies,
                        )
                        db.add(config)
                        await db.flush()
                        run = AuditRun(
                            base_url=sched.url,
                            mode=sched.mode,
                            status=AuditStatus.pending,
                            config_id=config.id,
                        )
                        db.add(run)
                        # Advance next_run_at
                        if sched.frequency == "daily":
                            sched.next_run_at = sched.next_run_at + timedelta(days=1)
                        elif sched.frequency == "weekly":
                            sched.next_run_at = sched.next_run_at + timedelta(weeks=1)
                        else:  # monthly
                            sched.next_run_at = sched.next_run_at + timedelta(days=30)
                        logger.info(f"Scheduler: launched audit for {sched.url} (schedule {sched.id})")
                    except Exception as e:
                        logger.warning(f"Scheduler: failed to launch audit for {sched.url}: {e}")
                await db.commit()
        except Exception as e:
            logger.warning(f"Scheduler loop error: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Odit - Tracking Auditor",
    description="Local-first website tracking and analytics implementation auditor",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Configure shared templates with custom filters
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["basename"] = os.path.basename
templates.env.filters["fromjson"] = json.loads

# Inject templates into web routes module so it uses the same instance
web_routes.templates = templates

# Include API routers
app.include_router(audits.router)
app.include_router(pages.router)
app.include_router(issues.router)
app.include_router(vendors.router)
app.include_router(exports.router)
app.include_router(comparisons.router)
app.include_router(settings_api.router)
app.include_router(suggestions.router)
app.include_router(events.router)
app.include_router(help_api.router)

# Include Web (template) router
app.include_router(web_routes.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "odit-app"}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return templates.TemplateResponse(
        "404.html", {"request": request}, status_code=404
    )
