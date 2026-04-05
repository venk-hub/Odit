"""
Crawl engine: orchestrates the full crawl for an AuditRun using Playwright.
"""
import os
import re
import json
import time
import fnmatch
import logging
from collections import deque
from datetime import datetime
from typing import List, Dict, Set, Optional, Tuple
from urllib.parse import urlparse, urljoin, urldefrag

from sqlalchemy.orm import Session

from worker.config import get_settings
from worker.crawler.page_analyzer import (
    compute_page_group,
    extract_page_metadata,
    extract_storage,
    extract_cookies,
    extract_script_srcs,
    extract_window_globals,
    extract_data_layer,
    take_screenshot,
    extract_service_workers,
    extract_iframe_signals,
    extract_links,
)
from worker.detectors.vendor_detector import detect_vendors_from_page_data, is_tracking_url, get_vendor_key_for_url
from worker.emit import emit

logger = logging.getLogger("odit.worker.engine")
settings = get_settings()

MAX_RETRIES = 1
PAGE_TIMEOUT = 15000  # ms
NAV_TIMEOUT = 15000  # ms
JS_SETTLE_MS = 1000  # ms to wait after load for JS to fire (was 2000)


def matches_any_pattern(url: str, patterns: List[str]) -> bool:
    parsed = urlparse(url)
    path = parsed.path
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
        if pat in path:
            return True
    return False


def should_visit(
    url: str,
    allowed_domains: List[str],
    include_patterns: List[str],
    exclude_patterns: List[str],
    base_url: str,
) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc not in allowed_domains:
        return False
    if exclude_patterns and matches_any_pattern(url, exclude_patterns):
        return False
    if include_patterns and not matches_any_pattern(url, include_patterns):
        return False
    return True


def run_crawl(db: Session, audit_run, audit_config) -> None:
    """
    Main crawl function. Crawls the site using Playwright with BFS.
    All page data is stored in the DB. Artifacts are saved to disk.
    """
    from app.models import (
        AuditRun, PageVisit, NetworkRequest, ConsoleEvent,
        DetectedVendor, AuditStatus
    )

    audit_id = str(audit_run.id)
    base_url = audit_run.base_url
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc

    allowed_domains = list(audit_config.allowed_domains or [base_domain])
    if base_domain not in allowed_domains:
        allowed_domains.append(base_domain)

    max_pages = audit_config.max_pages
    max_depth = audit_config.max_depth
    consent_behavior = audit_config.consent_behavior
    device_type = audit_config.device_type
    include_patterns = list(audit_config.include_patterns or [])
    exclude_patterns = list(audit_config.exclude_patterns or [])
    seed_urls = list(audit_config.seed_urls or [])
    mode = audit_run.mode

    # Set up artifact directory
    artifact_dir = os.path.join(settings.DATA_DIR, "audits", audit_id)
    screenshots_dir = os.path.join(artifact_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    # Seed URLs
    if seed_urls:
        queue = deque([(url, 0) for url in seed_urls])
        visited: Set[str] = set(seed_urls)
    else:
        queue = deque([(base_url, 0)])
        visited: Set[str] = {base_url}

    pages_discovered = 1 if not seed_urls else len(seed_urls)
    pages_crawled = 0
    pages_failed = 0

    # Update discovered count
    audit_run.pages_discovered = pages_discovered
    db.commit()

    emit(db, audit_run.id, "crawl_start",
         f"Starting crawl of {base_url}",
         {"base_url": base_url, "mode": str(mode), "max_pages": max_pages, "max_depth": max_depth,
          "device": device_type, "consent": consent_behavior})
    db.commit()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        proxy_settings = None
        if settings.USE_PROXY:
            proxy_settings = {
                "server": f"http://{settings.PROXY_HOST}:{settings.PROXY_PORT}",
            }

        launch_kwargs = {"headless": True}
        if proxy_settings:
            launch_kwargs["proxy"] = proxy_settings

        browser = p.chromium.launch(**launch_kwargs)

        # Create ONE context for the entire crawl (reused across all pages)
        # This avoids the overhead of spinning up a new context per page.
        context_kwargs: Dict = {"ignore_https_errors": True}
        if device_type == "mobile":
            context_kwargs.update({
                "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
                "viewport": {"width": 390, "height": 844},
                "device_scale_factor": 3,
                "is_mobile": True,
            })
        else:
            context_kwargs["viewport"] = {"width": 1440, "height": 900}
        if audit_config.auth_storage_state:
            context_kwargs["storage_state"] = audit_config.auth_storage_state

        context = browser.new_context(**context_kwargs)

        if audit_config.auth_cookies and not audit_config.auth_storage_state:
            try:
                context.add_cookies(audit_config.auth_cookies)
            except Exception as e:
                logger.warning(f"Failed to inject auth cookies: {e}")

        try:
            while queue and pages_crawled < max_pages:
                # Check for cancellation
                db.refresh(audit_run)
                if audit_run.status == AuditStatus.cancelled:
                    logger.info(f"Audit {audit_id} cancelled, stopping crawl")
                    break

                url, depth = queue.popleft()
                logger.info(f"Crawling [{pages_crawled+1}/{max_pages}] depth={depth}: {url}")
                emit(db, audit_run.id, "page_start",
                     f"Crawling page {pages_crawled+1}: {url}",
                     {"url": url, "depth": depth, "page_num": pages_crawled + 1})
                db.commit()

                page = context.new_page()

                # Intercept dataLayer pushes before any page scripts run
                page.add_init_script("""
                    window.__oditDLBuf = [];
                    (function() {
                        if (!window.dataLayer) window.dataLayer = [];
                        var _origPush = Array.prototype.push.bind(window.dataLayer);
                        window.dataLayer.push = function() {
                            for (var i = 0; i < arguments.length; i++) {
                                try { window.__oditDLBuf.push(JSON.parse(JSON.stringify(arguments[i]))); } catch(e) {}
                            }
                            return _origPush.apply(window.dataLayer, arguments);
                        };
                    })();
                """)

                # Collect network events
                page_requests: List[Dict] = []
                console_messages: List[Dict] = []
                redirect_chain: List[str] = []

                def on_response(response):
                    try:
                        req = response.request
                        post_data = None
                        if req.method in ("POST", "PUT", "PATCH"):
                            try:
                                post_data = req.post_data
                            except Exception:
                                pass
                        timing_ms = None
                        try:
                            t = req.timing
                            if t and t.get("responseEnd", 0) > 0:
                                timing_ms = t["responseEnd"]
                        except Exception:
                            pass
                        page_requests.append({
                            "url": response.url,
                            "method": req.method,
                            "status_code": response.status,
                            "resource_type": req.resource_type,
                            "request_headers": dict(req.headers),
                            "response_headers": dict(response.headers),
                            "post_data": post_data,
                            "failed": response.status >= 400,
                            "failure_reason": None,
                            "timing_ms": timing_ms,
                        })
                    except Exception as e:
                        logger.debug(f"Response handler error: {e}")

                def on_request_failed(request):
                    try:
                        page_requests.append({
                            "url": request.url,
                            "method": request.method,
                            "status_code": None,
                            "resource_type": request.resource_type,
                            "request_headers": dict(request.headers),
                            "response_headers": {},
                            "failed": True,
                            "failure_reason": request.failure,
                        })
                    except Exception as e:
                        logger.debug(f"Request failed handler error: {e}")

                def on_console(msg):
                    try:
                        console_messages.append({
                            "level": msg.type,
                            "message": msg.text,
                            "source_url": msg.location.get("url") if msg.location else None,
                            "line_number": msg.location.get("lineNumber") if msg.location else None,
                            "column_number": msg.location.get("columnNumber") if msg.location else None,
                        })
                    except Exception as e:
                        logger.debug(f"Console handler error: {e}")

                page.on("response", on_response)
                page.on("requestfailed", on_request_failed)
                page.on("console", on_console)

                page_visit = None
                error_message = None
                status_code = None
                final_url = url
                load_time_ms = None

                # Attempt navigation with retries
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        t_start = time.time()
                        response = page.goto(
                            url,
                            timeout=NAV_TIMEOUT,
                            wait_until="domcontentloaded",
                        )
                        load_time_ms = (time.time() - t_start) * 1000
                        status_code = response.status if response else None
                        final_url = page.url

                        # Handle consent banner if configured
                        if consent_behavior == "accept_consent":
                            _try_accept_consent(page)

                        # Wait a bit for JS to fire
                        page.wait_for_timeout(JS_SETTLE_MS)

                        # Journey audit: execute AI-resolved NL steps on seed pages
                        journey_instructions = list(getattr(audit_config, "journey_instructions", None) or [])
                        if mode == "journey_audit" and journey_instructions and depth == 0:
                            _execute_journey_steps(page, journey_instructions, url)

                        error_message = None
                        break
                    except Exception as e:
                        error_message = str(e)
                        logger.warning(f"Navigation attempt {attempt+1} failed for {url}: {e}")
                        if attempt < MAX_RETRIES:
                            page.wait_for_timeout(1000)

                # Extract page data
                screenshot_path = None
                meta = {}
                storage = {"local_storage_keys": [], "session_storage_keys": []}
                cookies_data = []
                script_srcs = []
                window_globals_found = []
                data_layer_data = {}
                discovered_links = []

                if not error_message:
                    try:
                        meta = extract_page_metadata(page)
                    except Exception as e:
                        logger.warning(f"Meta extraction failed: {e}")

                    try:
                        storage = extract_storage(page)
                    except Exception as e:
                        logger.warning(f"Storage extraction failed: {e}")

                    try:
                        cookies_data = extract_cookies(context)
                    except Exception as e:
                        logger.warning(f"Cookie extraction failed: {e}")

                    try:
                        script_srcs = extract_script_srcs(page)
                    except Exception as e:
                        logger.warning(f"Script extraction failed: {e}")

                    try:
                        window_globals_found = extract_window_globals(page)
                    except Exception as e:
                        logger.warning(f"Window globals extraction failed: {e}")

                    try:
                        data_layer_data = extract_data_layer(page)
                    except Exception as e:
                        logger.warning(f"Data layer extraction failed: {e}")

                    try:
                        iframe_signals = extract_iframe_signals(page)
                        # Merge iframe script srcs and globals into main lists
                        if iframe_signals["extra_script_srcs"]:
                            script_srcs = list(dict.fromkeys(script_srcs + iframe_signals["extra_script_srcs"]))
                        if iframe_signals["extra_globals"]:
                            window_globals_found = list(dict.fromkeys(window_globals_found + iframe_signals["extra_globals"]))
                        if iframe_signals["iframe_urls"]:
                            data_layer_data["_iframes"] = iframe_signals["iframe_urls"]
                    except Exception as e:
                        logger.warning(f"Iframe signal extraction failed: {e}")

                    try:
                        service_workers = extract_service_workers(page)
                        if service_workers:
                            data_layer_data["_service_workers"] = service_workers
                            # Inject SW script URLs into page_requests so vendor detection sees them
                            for sw in service_workers:
                                if sw.get("script_url"):
                                    page_requests.append({
                                        "url": sw["script_url"],
                                        "method": "GET",
                                        "status_code": None,
                                        "resource_type": "service_worker",
                                        "request_headers": {},
                                        "response_headers": {},
                                        "failed": False,
                                        "failure_reason": None,
                                    })
                    except Exception as e:
                        logger.warning(f"Service worker extraction failed: {e}")

                    # Screenshot
                    ss_filename = f"screenshot_{pages_crawled:04d}.png"
                    ss_path = os.path.join(screenshots_dir, ss_filename)
                    screenshot_path = take_screenshot(page, ss_path)

                    # Discover links for BFS (only if not at max depth and not journey mode)
                    if depth < max_depth and mode != "journey_audit":
                        try:
                            discovered_links = extract_links(page, base_domain)
                        except Exception as e:
                            logger.warning(f"Link extraction failed: {e}")

                # Close the page (context is reused across pages)
                try:
                    page.close()
                except Exception:
                    pass

                har_file_path = None

                # Compute page group
                page_group = compute_page_group(final_url or url)

                # Console error count
                console_error_count = sum(1 for m in console_messages if m["level"] == "error")
                failed_request_count = sum(1 for r in page_requests if r["failed"])

                # Create PageVisit
                pv = PageVisit(
                    audit_run_id=audit_run.id,
                    url=url,
                    final_url=final_url,
                    status_code=status_code,
                    page_title=meta.get("title"),
                    meta_description=meta.get("meta_description"),
                    canonical_url=meta.get("canonical_url"),
                    page_group=page_group,
                    load_time_ms=load_time_ms,
                    screenshot_path=screenshot_path,
                    har_path=har_file_path,
                    console_error_count=console_error_count,
                    failed_request_count=failed_request_count,
                    cookies=[c["name"] for c in cookies_data],
                    cookies_detail=cookies_data,
                    data_layer=data_layer_data if data_layer_data else None,
                    local_storage_keys=storage["local_storage_keys"],
                    session_storage_keys=storage["session_storage_keys"],
                    script_srcs=script_srcs,
                    redirect_chain=redirect_chain,
                    crawled_at=datetime.utcnow(),
                    error_message=error_message,
                )
                db.add(pv)
                db.flush()

                # Store network requests
                page_nr_list = []  # (vendor_key, nr) for back-linking after vendor detection
                for req_data in page_requests:
                    req_url = req_data["url"]
                    is_tracking = is_tracking_url(req_url)
                    vendor_key = get_vendor_key_for_url(req_url) if is_tracking else None

                    nr = NetworkRequest(
                        page_visit_id=pv.id,
                        audit_run_id=audit_run.id,
                        url=req_url[:2000],
                        method=req_data["method"],
                        status_code=req_data["status_code"],
                        resource_type=req_data.get("resource_type"),
                        request_headers=req_data.get("request_headers", {}),
                        response_headers=req_data.get("response_headers", {}),
                        post_data=req_data.get("post_data"),
                        failed=req_data["failed"],
                        failure_reason=req_data.get("failure_reason"),
                        is_tracking_related=is_tracking,
                        timing_ms=req_data.get("timing_ms"),
                        captured_at=datetime.utcnow(),
                    )
                    db.add(nr)
                    if vendor_key:
                        page_nr_list.append((vendor_key, nr))

                # Store console events
                for cm in console_messages:
                    ce = ConsoleEvent(
                        page_visit_id=pv.id,
                        audit_run_id=audit_run.id,
                        level=cm["level"],
                        message=cm["message"][:2000],
                        source_url=cm.get("source_url"),
                        line_number=cm.get("line_number"),
                        column_number=cm.get("column_number"),
                        captured_at=datetime.utcnow(),
                    )
                    db.add(ce)

                # Detect vendors for this page
                cookie_names = [c["name"] for c in cookies_data]
                req_urls = [r["url"] for r in page_requests]
                page_vendor_matches = detect_vendors_from_page_data(
                    network_request_urls=req_urls,
                    script_srcs=script_srcs,
                    window_globals=window_globals_found,
                    cookie_names=cookie_names,
                )

                created_dvs = []
                for vm in page_vendor_matches:
                    dv = DetectedVendor(
                        audit_run_id=audit_run.id,
                        page_visit_id=pv.id,
                        vendor_key=vm.vendor_key,
                        vendor_name=vm.vendor_name,
                        category=vm.category,
                        detection_method=vm.detection_method,
                        evidence=vm.evidence,
                        page_count=1,
                        detected_at=datetime.utcnow(),
                    )
                    db.add(dv)
                    created_dvs.append(dv)
                    emit(db, audit_run.id, "vendor_detected",
                         f"Detected: {vm.vendor_name} ({vm.category}) via {vm.detection_method}",
                         {"vendor_key": vm.vendor_key, "vendor_name": vm.vendor_name,
                          "category": vm.category, "method": vm.detection_method,
                          "page_url": url})

                # Link NetworkRequests to their DetectedVendor (enables performance stats)
                if page_nr_list and created_dvs:
                    db.flush()  # ensure DetectedVendor records have IDs
                    vkey_to_dv_id = {dv.vendor_key: dv.id for dv in created_dvs}
                    for vkey, nr in page_nr_list:
                        if vkey in vkey_to_dv_id:
                            nr.vendor_id = vkey_to_dv_id[vkey]

                # Emit tracking requests (up to 5 per page to avoid noise)
                tracking_reqs = [r for r in page_requests if is_tracking_url(r["url"])]
                for req in tracking_reqs[:5]:
                    vendor_key = get_vendor_key_for_url(req["url"])
                    emit(db, audit_run.id, "request_captured",
                         f"Tracking request: {req['url'][:80]}",
                         {"url": req["url"], "method": req["method"],
                          "status": req.get("status_code"), "vendor": vendor_key,
                          "has_payload": bool(req.get("post_data"))})
                if len(tracking_reqs) > 5:
                    emit(db, audit_run.id, "request_captured",
                         f"...and {len(tracking_reqs) - 5} more tracking requests on this page",
                         {"count": len(tracking_reqs)})

                if error_message:
                    pages_failed += 1
                    emit(db, audit_run.id, "page_error",
                         f"Failed: {url} — {error_message[:120]}",
                         {"url": url, "error": error_message})
                else:
                    pages_crawled += 1
                    tracking_count = len(tracking_reqs)
                    vendor_count = len(page_vendor_matches)
                    load_ms = round(load_time_ms) if load_time_ms else 0
                    dl_keys = list(data_layer_data.keys()) if data_layer_data else []
                    emit(db, audit_run.id, "page_complete",
                         f"Done: {url} — {tracking_count} tracking req{'s' if tracking_count != 1 else ''}, "
                         f"{vendor_count} vendor{'s' if vendor_count != 1 else ''} in {load_ms}ms"
                         + (f", data layer: {', '.join(dl_keys)}" if dl_keys else ""),
                         {"url": url, "tracking_requests": tracking_count,
                          "vendors": vendor_count, "load_ms": load_ms,
                          "console_errors": console_error_count,
                          "data_layer_keys": dl_keys, "cookies": len(cookies_data)})

                # Enqueue new links
                for link in discovered_links:
                    clean_link, _ = urldefrag(link)
                    if clean_link not in visited and should_visit(
                        clean_link, allowed_domains, include_patterns, exclude_patterns, base_url
                    ):
                        visited.add(clean_link)
                        queue.append((clean_link, depth + 1))
                        pages_discovered += 1

                # Update run progress
                audit_run.pages_discovered = pages_discovered
                audit_run.pages_crawled = pages_crawled
                audit_run.pages_failed = pages_failed
                db.commit()

        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.close()

    # Aggregate vendors at audit level
    _aggregate_audit_vendors(db, audit_run)
    db.commit()


def _try_accept_consent(page) -> None:
    """Try to find and click common consent accept buttons across major CMPs."""
    selectors = [
        # OneTrust
        "#onetrust-accept-btn-handler",
        # Cookiebot
        "#CybotCookiebotDialogBodyButtonAccept",
        ".CybotCookiebotDialogBodyButton[id*='Accept']",
        # Didomi
        "#didomi-notice-agree-button",
        "button.didomi-components-button--filled",
        # TrustArc
        "#truste-consent-button",
        ".truste_overlay .pdynamicbutton a",
        # Quantcast
        ".qc-cmp2-summary-buttons button[mode='primary']",
        # CookieYes / CookieLaw
        ".cky-btn-accept",
        ".cookielawinfo-button-accept",
        # Osano
        "button.osano-cm-accept-all",
        # Borlabs Cookie
        "#BorlabsCookieBtn",
        ".borlabs-cookie .cookie-box button",
        # Civic Cookie Control
        "#ccc-notify-accept",
        "#ccc-accept-settings",
        # Termly
        "[id*='termly'] button[class*='accept']",
        # Klaro
        ".klaro button.cm-btn-success",
        # Moove GDPR plugin (WordPress)
        "#moove_gdpr_cookie_modal_save_settings_button",
        # Generic id/class patterns
        "button[id*='accept-all']",
        "button[id*='acceptAll']",
        "button[class*='accept-all']",
        "button[class*='acceptAll']",
        "button[id*='cookie-accept']",
        "button[class*='cookie-accept']",
        "[data-testid='cookie-accept']",
        "[data-testid='accept-all']",
        "a[id*='accept']",
        ".cb-enable",
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click(timeout=2000)
                page.wait_for_timeout(800)
                return
        except Exception:
            continue

    # Text-content fallback: find a visible button/link whose text is a common accept phrase
    try:
        found = page.evaluate("""() => {
            const phrases = ['accept all', 'accept all cookies', 'i accept', 'i agree', 'agree to all',
                             'allow all', 'allow all cookies', 'allow cookies', 'got it', 'ok, i agree',
                             'agree & proceed', 'consent to all'];
            const els = Array.from(document.querySelectorAll('button, a[role="button"], [role="button"]'));
            for (const el of els) {
                const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                if (phrases.some(p => text === p || text.startsWith(p))) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        el.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        if found:
            page.wait_for_timeout(800)
    except Exception:
        pass


def _execute_journey_steps(page, instructions: list, page_url: str) -> None:
    """
    Convert natural language journey instructions to Playwright actions via Claude
    and execute them safely. Each step is independently fault-tolerant.
    """
    from worker.ai.claude_client import nl_to_playwright_actions

    for instruction in instructions:
        try:
            # Get a brief HTML snippet to give Claude context
            html_snippet = ""
            try:
                html_snippet = page.evaluate("() => document.body.innerHTML.slice(0, 2000)")
            except Exception:
                pass

            actions = nl_to_playwright_actions(instruction, html_snippet)
            if not actions:
                logger.info(f"Journey: no actions generated for instruction '{instruction}'")
                continue

            logger.info(f"Journey: executing {len(actions)} actions for '{instruction}' on {page_url}")
            for action in actions:
                act = action.get("action", "")
                selector = action.get("selector", "")
                desc = action.get("description", act)
                try:
                    if act == "click" and selector:
                        page.click(selector, timeout=5000)
                        page.wait_for_timeout(1000)
                    elif act == "fill" and selector:
                        page.fill(selector, action.get("value", ""), timeout=5000)
                    elif act == "wait_for_selector" and selector:
                        page.wait_for_selector(selector, timeout=5000)
                    elif act == "wait_for_timeout":
                        ms = min(int(action.get("timeout", 1000)), 5000)
                        page.wait_for_timeout(ms)
                    elif act == "goto":
                        target = action.get("url", "")
                        if target:
                            page.goto(target, timeout=15000, wait_until="domcontentloaded")
                            page.wait_for_timeout(1000)
                    elif act == "scroll":
                        page.evaluate("window.scrollBy(0, window.innerHeight)")
                        page.wait_for_timeout(500)
                    logger.debug(f"Journey action completed: {desc}")
                except Exception as e:
                    logger.warning(f"Journey action '{act}' failed (continuing): {e}")
        except Exception as e:
            logger.warning(f"Journey step failed for instruction '{instruction}': {e}")


def _aggregate_audit_vendors(db: Session, audit_run) -> None:
    """
    Aggregate page-level vendor detections to audit-level (page_visit_id=None)
    with page_count set to how many pages detected it.
    """
    from sqlalchemy import func
    from app.models import DetectedVendor

    # Query page-level vendors grouped by vendor_key
    rows = (
        db.query(
            DetectedVendor.vendor_key,
            DetectedVendor.vendor_name,
            DetectedVendor.category,
            DetectedVendor.detection_method,
            func.count(DetectedVendor.id).label("page_count"),
        )
        .filter(
            DetectedVendor.audit_run_id == audit_run.id,
            DetectedVendor.page_visit_id != None,
        )
        .group_by(
            DetectedVendor.vendor_key,
            DetectedVendor.vendor_name,
            DetectedVendor.category,
            DetectedVendor.detection_method,
        )
        .all()
    )

    # Remove any existing audit-level vendors
    db.query(DetectedVendor).filter(
        DetectedVendor.audit_run_id == audit_run.id,
        DetectedVendor.page_visit_id == None,
    ).delete()

    # Get example evidence for each vendor
    for row in rows:
        example = (
            db.query(DetectedVendor)
            .filter(
                DetectedVendor.audit_run_id == audit_run.id,
                DetectedVendor.vendor_key == row.vendor_key,
                DetectedVendor.page_visit_id != None,
            )
            .first()
        )
        evidence = example.evidence if example else {}

        audit_vendor = DetectedVendor(
            audit_run_id=audit_run.id,
            page_visit_id=None,
            vendor_key=row.vendor_key,
            vendor_name=row.vendor_name,
            category=row.category,
            detection_method=row.detection_method,
            evidence=evidence,
            page_count=row.page_count,
            detected_at=datetime.utcnow(),
        )
        db.add(audit_vendor)
