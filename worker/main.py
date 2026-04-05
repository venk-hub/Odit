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
from worker.emit import emit

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
        emit(db, run.id, "rule_engine", "Running issue detection rules across all crawled pages...")
        db.commit()
        try:
            run_all_rules(db, run)
            from app.models import Issue
            issue_list = db.query(Issue).filter(Issue.audit_run_id == run.id).all()
            counts = {}
            for iss in issue_list:
                counts[iss.severity] = counts.get(iss.severity, 0) + 1
            summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items(), key=lambda x: ["critical","high","medium","low"].index(x[0]) if x[0] in ["critical","high","medium","low"] else 9))
            emit(db, run.id, "rule_engine",
                 f"Rules complete — {len(issue_list)} issue{'s' if len(issue_list) != 1 else ''} found"
                 + (f" ({summary})" if summary else ""),
                 {"total": len(issue_list), "by_severity": counts})
            db.commit()
            # Emit each issue as its own event
            for iss in issue_list:
                emit(db, run.id, "issue_flagged",
                     f"[{iss.severity.upper()}] {iss.title}",
                     {"severity": iss.severity, "category": iss.category,
                      "title": iss.title, "affected_url": iss.affected_url})
            db.commit()
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
        emit(db, run.id, "export_start", "Generating reports and exports...")
        db.commit()

        try:
            excel_path = os.path.join(artifact_dir, "audit_report.xlsx")
            generate_excel(db, run, excel_path)
            register_artifact(db, run.id, "excel", excel_path)
            emit(db, run.id, "export_generated", "Excel workbook ready (9 sheets)", {"file": "audit_report.xlsx"})
            db.commit()
        except Exception as e:
            logger.exception(f"Excel export failed: {e}")

        try:
            json_path = os.path.join(artifact_dir, "audit_summary.json")
            generate_json_summary(db, run, json_path)
            register_artifact(db, run.id, "report_json", json_path)
            emit(db, run.id, "export_generated", "JSON summary ready", {"file": "audit_summary.json"})
            db.commit()
        except Exception as e:
            logger.exception(f"JSON export failed: {e}")

        try:
            md_path = os.path.join(artifact_dir, "audit_summary.md")
            generate_markdown_report(db, run, md_path)
            register_artifact(db, run.id, "report_md", md_path)
            emit(db, run.id, "export_generated", "Markdown report ready", {"file": "audit_summary.md"})
            db.commit()
        except Exception as e:
            logger.exception(f"Markdown export failed: {e}")

        try:
            html_path = os.path.join(artifact_dir, "audit_summary.html")
            generate_html_report(db, run, html_path)
            register_artifact(db, run.id, "report_html", html_path)
            emit(db, run.id, "export_generated", "HTML report ready", {"file": "audit_summary.html"})
            db.commit()
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
            emit(db, run.id, "crawl_complete",
                 f"Audit complete — {run.pages_crawled} pages crawled",
                 {"pages_crawled": run.pages_crawled, "pages_failed": run.pages_failed})
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
        enrich_issue, infer_unknown_domains, generate_narrative_summary,
        generate_remediation_steps, analyze_tracking_payloads, scan_requests_for_pii,
        reset_session_tokens, get_session_tokens,
    )
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        # Fall back to key stored in DB via the settings UI
        try:
            from app.models.setting import AppSetting
            setting = db.query(AppSetting).filter(AppSetting.key == "anthropic_api_key").first()
            if setting and setting.value:
                api_key = setting.value.strip()
                logger.info("Using Anthropic API key from database settings")
        except Exception as e:
            logger.warning(f"Could not read API key from database: {e}")

    if not api_key:
        logger.info("No Anthropic API key found (env or database) — skipping AI enrichment")
        emit(db, run.id, "ai_call", "Skipping AI enrichment — no API key configured")
        db.commit()
        return

    # Pass the resolved key into the environment so _get_client() picks it up
    os.environ["ANTHROPIC_API_KEY"] = api_key

    audit_id = run.id
    reset_session_tokens()
    logger.info(f"Running AI enrichment for audit {audit_id}")
    emit(db, run.id, "ai_call", "Starting AI enrichment (Claude Haiku)...")
    db.commit()

    # Step 1: Batch-enrich all issues in one set of API calls (chunks of 20)
    issues = db.query(Issue).filter(Issue.audit_run_id == audit_id).all()
    if issues:
        emit(db, run.id, "ai_call",
             f"Enriching {len(issues)} issue{'s' if len(issues) != 1 else ''} with AI analysis...",
             {"count": len(issues)})
        db.commit()

        from worker.ai.claude_client import batch_enrich_issues
        issues_data = [
            {
                "title": iss.title,
                "category": iss.category,
                "severity": iss.severity,
                "affected_vendor_key": iss.affected_vendor_key,
                "description": iss.description,
            }
            for iss in issues
        ]
        enrichments = batch_enrich_issues(issues_data)
        enriched_count = 0
        for issue, enrichment in zip(issues, enrichments):
            if not enrichment:
                continue
            if enrichment.get("description"):
                issue.description = enrichment["description"]
            if enrichment.get("likely_cause"):
                issue.likely_cause = enrichment["likely_cause"]
            if enrichment.get("recommendation"):
                issue.recommendation = enrichment["recommendation"]
            if enrichment.get("remediation_steps"):
                issue.remediation_steps = enrichment["remediation_steps"]
            enriched_count += 1
        if enriched_count:
            db.commit()
            logger.info(f"AI batch-enriched {enriched_count} issues for audit {audit_id}")

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
        emit(db, run.id, "ai_call",
             f"Inferring purpose of {len(unknown_domains)} unrecognised third-party domain{'s' if len(unknown_domains) != 1 else ''}...",
             {"count": len(unknown_domains)})
        db.commit()
        inferred = infer_unknown_domains(unknown_domains)
        if inferred:
            emit(db, run.id, "ai_call",
                 f"Identified {len(inferred)} unknown domain{'s' if len(inferred) != 1 else ''} via AI",
                 {"domains": list(inferred.keys())[:10]})
            db.commit()
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

    # Steps 2b+2c: Single-pass over network requests — PII regex scan + vendor payload grouping.
    # One DB query, one Python loop, one AI call total. No per-request API calls.
    try:
        from urllib.parse import urlparse as _up, parse_qs as _pqs
        from datetime import datetime as _dt

        base_netloc = _up(run.base_url).netloc
        base_bare = base_netloc.lstrip("www.")

        # Build domain → vendor map once.
        # Evidence stores matched_domain (string) or domains (list) or ai_inferred domain.
        # Also load signature domains from vendors.yaml so we catch all known CDN domains.
        all_vendors = db.query(DetectedVendor).filter(
            DetectedVendor.audit_run_id == audit_id,
            DetectedVendor.page_visit_id == None,
        ).all()

        # Load vendor signature domains from YAML (key → [domains])
        _sig_domains: dict = {}
        try:
            import yaml as _yaml
            _sig_path = os.path.join(os.path.dirname(__file__), "detectors", "vendors.yaml")
            with open(_sig_path) as _f:
                _sig_data = _yaml.safe_load(_f)
            for _sig in _sig_data.get("vendors", []):
                _sig_domains[_sig["key"]] = _sig.get("signatures", {}).get("domains", [])
        except Exception:
            pass

        domain_to_vendor: dict = {}
        for v in all_vendors:
            ev = v.evidence or {}
            # From evidence: list of domains
            for d in ev.get("domains", []):
                domain_to_vendor[d] = v
            # From evidence: matched_domain (single string)
            md = ev.get("matched_domain", "")
            if md:
                domain_to_vendor[md] = v
            # From signature registry: all known CDN/API domains for this vendor key
            for d in _sig_domains.get(v.vendor_key, []):
                domain_to_vendor[d] = v
            # AI-inferred vendors
            if v.detection_method == "ai_inferred":
                d = ev.get("domain", "")
                if d:
                    domain_to_vendor[d] = v

        # Single minimal query — only columns we need
        raw_rows = db.query(
            NetworkRequest.url,
            NetworkRequest.method,
            NetworkRequest.post_data,
            NetworkRequest.resource_type,
        ).filter(
            NetworkRequest.audit_run_id == audit_id
        ).all()

        total_requests = len(raw_rows)

        # Per-vendor buckets: deduplicated by (host + path) so we never send
        # 500 identical GA beacon hits — just unique endpoint patterns
        vendor_request_map: dict = {}   # key → {name, category, seen_paths: set, requests: []}
        pii_scan_dedupe: list = []       # deduplicated subset for PII regex
        seen_url_patterns: set = set()

        for row in raw_rows:
            url = row.url or ""
            body = row.post_data or ""
            rtype = row.resource_type or ""

            try:
                parsed = _up(url)
                host = parsed.netloc
                path = parsed.path
            except Exception:
                continue

            # ── PII scan: deduplicate by host+path, cap at 500 unique patterns ──
            pat = f"{host}{path}"
            if pat not in seen_url_patterns and len(seen_url_patterns) < 500:
                seen_url_patterns.add(pat)
                pii_scan_dedupe.append({"url": url, "post_data": body})

            # ── Payload grouping: only tracking-relevant resource types ──
            if rtype not in ("xhr", "fetch", "beacon", "ping", "script"):
                continue
            if base_bare in host:
                continue  # skip first-party

            # Match to vendor
            matched = None
            for d, v in domain_to_vendor.items():
                if d in host or host.endswith("." + d) or host == d:
                    matched = v
                    break

            if matched:
                key = matched.vendor_key
                if key not in vendor_request_map:
                    vendor_request_map[key] = {
                        "name": matched.vendor_name,
                        "category": matched.category or "other",
                        "seen_paths": set(),
                        "requests": [],
                    }
            else:
                key = f"unknown_{host.replace('.', '_').replace('-', '_')}"
                if key not in vendor_request_map:
                    vendor_request_map[key] = {
                        "name": host, "category": "unknown",
                        "seen_paths": set(), "requests": [],
                    }

            entry = vendor_request_map[key]
            # Only keep one example per unique path (deduplicates repeated beacons)
            if path not in entry["seen_paths"] and len(entry["requests"]) < 8:
                entry["seen_paths"].add(path)
                entry["requests"].append({
                    "url": url[:300],
                    "method": row.method or "GET",
                    "body": body[:400],
                })

        # ── PII regex scan (pure Python, no AI) ──
        pii_hits = scan_requests_for_pii(pii_scan_dedupe)
        if pii_hits:
            db.add(Issue(
                audit_run_id=audit_id,
                created_at=_dt.utcnow(),
                severity="critical",
                category="pii_in_requests",
                title=f"PII detected in network requests ({len(pii_hits)} instance(s))",
                description=(
                    f"Regex scan across {len(pii_scan_dedupe)} unique request patterns "
                    f"(from {total_requests} total) found {len(pii_hits)} PII instance(s). "
                    f"Types: {', '.join(sorted(set(h['pii_type'] for h in pii_hits)))}."
                ),
                evidence_refs=[{"findings": pii_hits[:20], "patterns_scanned": len(pii_scan_dedupe)}],
                likely_cause="PII embedded in tracking request URLs or POST bodies.",
                recommendation=(
                    "Review flagged requests. PII in tracking payloads may violate GDPR Article 5 "
                    "(data minimisation). Replace with pseudonymous identifiers or hashed values."
                ),
            ))
            db.commit()
            logger.info(f"PII scan: {len(pii_hits)} hits across {len(pii_scan_dedupe)} unique patterns")

        # ── AI payload analysis: ONE call covering all vendors ──
        vendor_request_map = {k: v for k, v in vendor_request_map.items() if v["requests"]}
        priority_cats = {"analytics", "pixel", "session_replay", "ab_testing", "tag_manager", "consent"}
        sorted_keys = sorted(
            vendor_request_map.keys(),
            key=lambda k: (0 if vendor_request_map[k]["category"] in priority_cats else 1,
                           -len(vendor_request_map[k]["requests"]))
        )[:15]
        analysis_input = {k: vendor_request_map[k] for k in sorted_keys}

        if analysis_input:
            vendor_count = len(analysis_input)
            req_count = sum(len(v["requests"]) for v in analysis_input.values())
            emit(db, run.id, "ai_call",
                 f"Analysing payloads: {vendor_count} vendor(s), {req_count} representative requests — 1 AI call",
                 {"vendors": sorted_keys[:10]})
            db.commit()

            site = _up(run.base_url).netloc
            payload_results = analyze_tracking_payloads(site, analysis_input)

            if payload_results:
                for vendor_key, analysis in payload_results.items():
                    # Update ALL records with this vendor_key (one per detection_method)
                    vendor_rows = db.query(DetectedVendor).filter(
                        DetectedVendor.audit_run_id == audit_id,
                        DetectedVendor.vendor_key == vendor_key,
                    ).all()
                    for v in vendor_rows:
                        ev = dict(v.evidence or {})
                        ev["payload_analysis"] = analysis
                        v.evidence = ev
                    pii = analysis.get("pii_detected", [])
                    if pii and analysis.get("pii_risk") in ("high", "critical"):
                        vname = analysis_input[vendor_key]["name"]
                        db.add(Issue(
                            audit_run_id=audit_id,
                            created_at=_dt.utcnow(),
                            severity="critical",
                            category="pii_in_requests",
                            title=f"PII transmitted to {vname} in network requests",
                            description=(
                                f"AI payload analysis found PII being sent to {vname}: "
                                f"{'; '.join(str(p) for p in pii[:5])}."
                            ),
                            evidence_refs=[{"vendor": vendor_key, "pii": pii, "analysis": analysis}],
                            likely_cause=analysis.get("notable", ""),
                            recommendation=(
                                "Ensure PII is not transmitted to third parties without explicit consent "
                                "and a valid legal basis under GDPR Article 6."
                            ),
                        ))
                db.commit()
                logger.info(f"Payload analysis complete: {len(payload_results)} vendors, 1 API call")
    except Exception as e:
        logger.warning(f"Payload analysis/PII scan failed: {e}")

    # Step 3: Generate narrative summary and store as an artifact
    from worker.exports.artifact_manager import get_artifact_dir, register_artifact
    from app.models import PageVisit

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

    # ── Collect richer evidence for the summary prompt ──────────────
    # 1. Top third-party request domains by hit count
    req_domain_counts: dict = {}
    sample_beacons: list = []
    all_reqs = db.query(NetworkRequest).filter(NetworkRequest.audit_run_id == audit_id).all()
    for req in all_reqs:
        try:
            netloc = urlparse(req.url).netloc
            if netloc and netloc != urlparse(run.base_url).netloc:
                req_domain_counts[netloc] = req_domain_counts.get(netloc, 0) + 1
            # Capture POST payloads to known tracking endpoints
            if (req.post_data and len(sample_beacons) < 6
                    and req.resource_type in ("fetch", "xhr", "other")):
                sample_beacons.append({
                    "url": req.url[:120],
                    "body": req.post_data[:300],
                })
        except Exception:
            pass
    top_domains = sorted(req_domain_counts.items(), key=lambda x: -x[1])[:15]

    # 2. Data layer keys found across all pages
    data_layer_summary: dict = {}  # layer_name -> list of sample keys
    cookie_names: set = set()
    pages_visited = db.query(PageVisit).filter(PageVisit.audit_run_id == audit_id).all()
    for page in pages_visited:
        if page.data_layer:
            for layer_name, layer_data in page.data_layer.items():
                if layer_name not in data_layer_summary:
                    data_layer_summary[layer_name] = set()
                if isinstance(layer_data, list):
                    for item in layer_data[:3]:
                        if isinstance(item, dict):
                            data_layer_summary[layer_name].update(item.keys())
                elif isinstance(layer_data, dict):
                    data_layer_summary[layer_name].update(layer_data.keys())
        if page.cookies_detail:
            for cookie in page.cookies_detail:
                if isinstance(cookie, dict) and cookie.get("name"):
                    cookie_names.add(cookie["name"])

    # Trim data layer keys
    data_layer_out = {
        name: sorted(list(keys))[:25]
        for name, keys in data_layer_summary.items()
        if keys
    }

    # 3. Vendor detection evidence (method + domains/scripts)
    vendor_evidence = []
    for v in vendors:
        ev = v.evidence or {}
        vendor_evidence.append({
            "name": v.vendor_name,
            "category": v.category,
            "method": v.detection_method,
            "domains": ev.get("domains", [])[:3],
            "scripts": ev.get("scripts", [])[:3],
            "globals": ev.get("globals", [])[:3],
            "cookies": ev.get("cookies", [])[:3],
            "pages": v.page_count,
        })

    emit(db, run.id, "ai_call", "Generating AI narrative summary...")
    db.commit()
    narrative = generate_narrative_summary({
        "base_url": run.base_url,
        "mode": run.mode.value if hasattr(run.mode, "value") else str(run.mode),
        "pages_crawled": run.pages_crawled or 0,
        "vendors": vendor_names,
        "vendor_evidence": vendor_evidence,
        "issue_counts": issue_counts,
        "top_issues": top_issues,
        "broken_domains": broken_domains,
        "top_request_domains": top_domains,
        "total_requests": len(all_reqs),
        "sample_beacons": sample_beacons,
        "data_layers": data_layer_out,
        "cookie_names": sorted(list(cookie_names))[:30],
    })

    if narrative:
        artifact_dir = get_artifact_dir(settings.DATA_DIR, str(audit_id))
        summary_path = os.path.join(artifact_dir, "ai_summary.md")
        with open(summary_path, "w") as f:
            f.write(f"# AI Audit Summary\n\n{narrative}\n")
        register_artifact(db, audit_id, "report_md", summary_path)
        emit(db, run.id, "ai_call", "AI narrative summary written")
        db.commit()
        logger.info(f"AI narrative summary written for audit {audit_id}")

    # Log session token usage summary
    usage = get_session_tokens()
    emit(db, run.id, "ai_call",
         f"AI enrichment complete — {usage['calls']} call{'s' if usage['calls'] != 1 else ''}, "
         f"{usage['total_tokens']} tokens (~${usage['estimated_cost_usd']:.4f})",
         {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
          "total_tokens": usage["total_tokens"], "calls": usage["calls"],
          "estimated_cost_usd": usage["estimated_cost_usd"]})
    db.commit()
    logger.info(
        f"[AI tokens] Session total: {usage['input_tokens']} in + {usage['output_tokens']} out "
        f"= {usage['total_tokens']} tokens across {usage['calls']} calls "
        f"(~${usage['estimated_cost_usd']:.5f})"
    )


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
