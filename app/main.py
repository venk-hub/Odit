from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
import logging
import os
import posixpath

from app.config import get_settings
from app.api import audits, pages, issues, vendors, exports, comparisons
from app.api import settings as settings_api
from app.web import routes as web_routes

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("odit.app")

app = FastAPI(
    title="Odit - Tracking Auditor",
    description="Local-first website tracking and analytics implementation auditor",
    version="1.0.0",
)

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Configure shared templates with custom filters
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["basename"] = os.path.basename

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
