"""
Worker entrypoint: polls the database for pending AuditRun jobs and processes them.
"""
import sys
import os
import time
import logging
from datetime import datetime

# Add project root to path so we can import app/ and worker/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.config import get_settings
from app.database import SyncSessionLocal
from app.models import AuditRun, AuditStatus

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("odit.worker")


def wait_for_db(max_attempts: int = 30, delay: int = 3) -> None:
    from sqlalchemy import text
    for attempt in range(1, max_attempts + 1):
        try:
            db = SyncSessionLocal()
            db.execute(text("SELECT 1"))
            db.close()
            logger.info("Database connection established.")
            return
        except Exception as e:
            logger.warning(f"Waiting for DB (attempt {attempt}/{max_attempts}): {e}")
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database after multiple attempts.")


def process_audit(audit_run_id: str) -> None:
    from worker.crawler.engine import run_crawl
    from worker.rules.rule_engine import run_all_rules
    from worker.exports.excel_exporter import generate_excel
    from worker.exports.report_exporter import generate_json_summary, generate_markdown_report, generate_html_report
    from worker.exports.artifact_manager import register_artifact, get_artifact_dir
    from app.models import AuditConfig

    db = SyncSessionLocal()
    try:
        run = db.query(AuditRun).filter(AuditRun.id == audit_run_id).first()
        if not run:
            logger.error(f"Audit run {audit_run_id} not found")
            return

        config = db.query(AuditConfig).filter(AuditConfig.id == run.config_id).first()
        if not config:
            logger.error(f"Audit config not found for run {audit_run_id}")
            run.status = AuditStatus.failed
            run.error_message = "Audit configuration not found"
            db.commit()
            return

        # Mark as running
        run.status = AuditStatus.running
        run.started_at = datetime.utcnow()
        db.commit()

        logger.info(f"Starting crawl for audit {audit_run_id} - {run.base_url}")

        # Crawl
        try:
            run_crawl(db, run, config)
        except Exception as e:
            logger.exception(f"Crawl failed for audit {audit_run_id}: {e}")
            db.refresh(run)
            run.status = AuditStatus.failed
            run.error_message = f"Crawl error: {str(e)[:500]}"
            run.completed_at = datetime.utcnow()
            db.commit()
            return

        # Check for cancellation
        db.refresh(run)
        if run.status == AuditStatus.cancelled:
            logger.info(f"Audit {audit_run_id} was cancelled")
            return

        logger.info(f"Running rules for audit {audit_run_id}")
        try:
            run_all_rules(db, run)
        except Exception as e:
            logger.exception(f"Rule engine failed for audit {audit_run_id}: {e}")

        # AI enrichment (optional — skipped gracefully if no API key)
        try:
            _run_ai_enrichment(db, run)
        except Exception as e:
            logger.warning(f"AI enrichment failed (non-fatal): {e}")

        # Generate exports
        logger.info(f"Generating exports for audit {audit_run_id}")
        artifact_dir = get_artifact_dir(settings.DATA_DIR, str(audit_run_id))

        try:
            excel_path = os.path.join(artifact_dir, "audit_report.xlsx")
            generate_excel(db, run, excel_path)
            register_artifact(db, run.id, "excel", excel_path)
        except Exception as e:
            logger.exception(f"Excel export failed: {e}")

        try:
            json_path = os.path.join(artifact_dir, "audit_summary.json")
            generate_json_summary(db, run, json_path)
            register_artifact(db, run.id, "report_json", json_path)
        except Exception as e:
            logger.exception(f"JSON export failed: {e}")

        try:
            md_path = os.path.join(artifact_dir, "audit_summary.md")
            generate_markdown_report(db, run, md_path)
            register_artifact(db, run.id, "report_md", md_path)
        except Exception as e:
            logger.exception(f"Markdown export failed: {e}")

        try:
            html_path = os.path.join(artifact_dir, "audit_summary.html")
            generate_html_report(db, run, html_path)
            register_artifact(db, run.id, "report_html", html_path)
        except Exception as e:
            logger.exception(f"HTML export failed: {e}")

        # Register screenshots as artifacts
        try:
            screenshots_dir = os.path.join(settings.DATA_DIR, "audits", str(audit_run_id), "screenshots")
            if os.path.exists(screenshots_dir):
                for fname in os.listdir(screenshots_dir):
                    if fname.endswith(".png"):
                        fpath = os.path.join(screenshots_dir, fname)
                        register_artifact(db, run.id, "screenshot", fpath)
        except Exception as e:
            logger.warning(f"Screenshot artifact registration failed: {e}")

        # Register HAR files
        try:
            har_dir = os.path.join(settings.DATA_DIR, "audits", str(audit_run_id), "har")
            if os.path.exists(har_dir):
                for fname in os.listdir(har_dir):
                    if fname.endswith(".har"):
                        fpath = os.path.join(har_dir, fname)
                        register_artifact(db, run.id, "har", fpath)
        except Exception as e:
            logger.warning(f"HAR artifact registration failed: {e}")

        # Mark completed
        db.refresh(run)
        if run.status != AuditStatus.cancelled:
            run.status = AuditStatus.completed
            run.completed_at = datetime.utcnow()
            db.commit()
            logger.info(f"Audit {audit_run_id} completed successfully")

    except Exception as e:
        logger.exception(f"Unexpected error processing audit {audit_run_id}: {e}")
        try:
            db.refresh(run)
            run.status = AuditStatus.failed
            run.error_message = str(e)[:500]
            run.completed_at = datetime.utcnow()
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _run_ai_enrichment(db, run) -> None:
    """Run all AI enrichment steps. Each step is independently fault-tolerant."""
    from app.models import Issue, NetworkRequest, DetectedVendor
    from worker.ai.claude_client import (
        enrich_issue, infer_unknown_domains, generate_narrative_summary
    )
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set — skipping AI enrichment")
        return

    audit_id = run.id
    logger.info(f"Running AI enrichment for audit {audit_id}")

    # Step 1: Enrich issues with better descriptions and recommendations
    issues = db.query(Issue).filter(Issue.audit_run_id == audit_id).all()
    enriched_count = 0
    for issue in issues:
        enrichment = enrich_issue({
            "category": issue.category,
            "title": issue.title,
            "severity": issue.severity,
            "affected_url": issue.affected_url,
            "affected_vendor_key": issue.affected_vendor_key,
            "evidence_refs": issue.evidence_refs or [],
            "description": issue.description,
            "likely_cause": issue.likely_cause,
            "recommendation": issue.recommendation,
        })
        if enrichment:
            if enrichment.get("description"):
                issue.description = enrichment["description"]
            if enrichment.get("likely_cause"):
                issue.likely_cause = enrichment["likely_cause"]
            if enrichment.get("recommendation"):
                issue.recommendation = enrichment["recommendation"]
            enriched_count += 1
    if enriched_count:
        db.commit()
        logger.info(f"AI enriched {enriched_count} issues for audit {audit_id}")

    # Step 2: Infer unknown third-party domains
    known_vendor_domains: set = set()
    for v in db.query(DetectedVendor).filter(DetectedVendor.audit_run_id == audit_id).all():
        evidence = v.evidence or {}
        for d in evidence.get("domains", []):
            known_vendor_domains.add(d)

    # Collect unique third-party domains from network requests not already identified
    from urllib.parse import urlparse
    from app.models import PageVisit
    base_domain = urlparse(run.base_url).netloc

    all_domains: set = set()
    for req in db.query(NetworkRequest).filter(NetworkRequest.audit_run_id == audit_id).all():
        try:
            netloc = urlparse(req.url).netloc
            if netloc and netloc != base_domain and netloc not in known_vendor_domains:
                all_domains.add(netloc)
        except Exception:
            pass

    unknown_domains = [d for d in all_domains if d][:40]
    if unknown_domains:
        inferred = infer_unknown_domains(unknown_domains)
        for domain, info in inferred.items():
            # Store as a DetectedVendor record marked as AI-inferred
            existing = (
                db.query(DetectedVendor)
                .filter(
                    DetectedVendor.audit_run_id == audit_id,
                    DetectedVendor.vendor_key == f"inferred_{domain.replace('.', '_')}",
                )
                .first()
            )
            if not existing:
                vendor = DetectedVendor(
                    audit_run_id=audit_id,
                    vendor_key=f"inferred_{domain.replace('.', '_')}",
                    vendor_name=info.get("name", domain),
                    category=info.get("category", "other"),
                    detection_method="ai_inferred",
                    evidence={"domain": domain, "ai_description": info.get("description", "")},
                    page_count=0,
                )
                db.add(vendor)
        db.commit()
        logger.info(f"AI inferred {len(inferred)} unknown vendors for audit {audit_id}")

    # Step 3: Generate narrative summary and store as an artifact
    from worker.exports.artifact_manager import get_artifact_dir, register_artifact

    vendors = db.query(DetectedVendor).filter(
        DetectedVendor.audit_run_id == audit_id,
        DetectedVendor.page_visit_id == None,
    ).all()
    vendor_names = [v.vendor_name for v in vendors]

    issue_counts: dict = {}
    for issue in issues:
        issue_counts[issue.severity] = issue_counts.get(issue.severity, 0) + 1

    top_issues = [i.title for i in sorted(issues, key=lambda x: (
        {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.severity, 4)
    ))[:8]]

    # Collect broken domains from high-severity issues
    broken_domains = list({
        urlparse(i.affected_url).netloc
        for i in issues
        if i.affected_url and i.severity in ("critical", "high")
    })[:8]

    narrative = generate_narrative_summary({
        "base_url": run.base_url,
        "mode": run.mode.value if hasattr(run.mode, "value") else str(run.mode),
        "pages_crawled": run.pages_crawled or 0,
        "vendors": vendor_names,
        "issue_counts": issue_counts,
        "top_issues": top_issues,
        "broken_domains": broken_domains,
    })

    if narrative:
        artifact_dir = get_artifact_dir(settings.DATA_DIR, str(audit_id))
        summary_path = os.path.join(artifact_dir, "ai_summary.md")
        with open(summary_path, "w") as f:
            f.write(f"# AI Audit Summary\n\n{narrative}\n")
        register_artifact(db, audit_id, "report_md", summary_path)
        logger.info(f"AI narrative summary written for audit {audit_id}")


def poll_loop() -> None:
    logger.info("Worker started. Polling for pending audit jobs...")
    while True:
        db = SyncSessionLocal()
        try:
            # Grab one pending job at a time
            run = (
                db.query(AuditRun)
                .filter(AuditRun.status == AuditStatus.pending)
                .order_by(AuditRun.created_at.asc())
                .with_for_update(skip_locked=True)
                .first()
            )

            if run:
                audit_id = run.id
                logger.info(f"Picked up audit job: {audit_id}")
                db.close()
                process_audit(str(audit_id))
            else:
                db.close()
                time.sleep(settings.WORKER_POLL_INTERVAL)

        except Exception as e:
            logger.exception(f"Poll loop error: {e}")
            try:
                db.close()
            except Exception:
                pass
            time.sleep(settings.WORKER_POLL_INTERVAL)


if __name__ == "__main__":
    wait_for_db()
    poll_loop()
