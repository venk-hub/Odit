"""
Rule engine: evaluates all issue detection rules against collected audit data.
"""
import logging
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

logger = logging.getLogger("odit.worker.rules")

TRACKING_RESOURCE_TYPES = {"script", "xhr", "fetch", "image", "other"}
AB_TESTING_CATEGORIES = {"ab_testing"}
TRACKING_CATEGORIES = {"analytics", "tag_manager", "pixel", "ab_testing"}


def run_all_rules(db: Session, audit_run) -> None:
    """Run all issue detection rules and persist Issue objects."""
    from app.models import (
        PageVisit, NetworkRequest, ConsoleEvent, DetectedVendor, Issue, AuditConfig
    )

    audit_id = audit_run.id
    config = db.query(AuditConfig).filter(AuditConfig.id == audit_run.config_id).first()

    # Load all data
    pages = db.query(PageVisit).filter(PageVisit.audit_run_id == audit_id).all()
    requests = db.query(NetworkRequest).filter(NetworkRequest.audit_run_id == audit_id).all()
    console_events = db.query(ConsoleEvent).filter(ConsoleEvent.audit_run_id == audit_id).all()
    # Audit-level vendors only
    vendors = (
        db.query(DetectedVendor)
        .filter(DetectedVendor.audit_run_id == audit_id, DetectedVendor.page_visit_id == None)
        .all()
    )
    # Page-level vendors
    page_vendors = (
        db.query(DetectedVendor)
        .filter(DetectedVendor.audit_run_id == audit_id, DetectedVendor.page_visit_id != None)
        .all()
    )

    issues: List[Issue] = []

    issues.extend(_rule_crawler_blocked(audit_run, pages, requests))
    issues.extend(_rule_no_tracking_detected(audit_run, pages, vendors))
    issues.extend(_rule_broken_tracking_request(audit_run, pages, requests, vendors))
    issues.extend(_rule_failed_script_load(audit_run, pages, requests, vendors))
    issues.extend(_rule_console_js_errors(audit_run, pages, console_events))
    issues.extend(_rule_missing_expected_vendor(audit_run, config, vendors))
    issues.extend(_rule_inconsistent_vendor_coverage(audit_run, pages, page_vendors))
    issues.extend(_rule_duplicate_pageview_signal(audit_run, pages, requests, page_vendors))
    issues.extend(_rule_consent_issue_no_interaction(audit_run, config, pages, page_vendors))
    issues.extend(_rule_ab_vendor_broken(audit_run, pages, requests, vendors))
    issues.extend(_rule_redirect_tracking_loss(audit_run, pages, page_vendors))
    issues.extend(_rule_template_inconsistency(audit_run, pages, page_vendors))
    issues.extend(_rule_network_request_destinations(audit_run, pages, requests, vendors))
    issues.extend(_rule_data_layer_audit(audit_run, pages))

    for issue in issues:
        db.add(issue)
    db.commit()

    logger.info(f"Rule engine generated {len(issues)} issues for audit {audit_id}")


def _make_issue(audit_run, **kwargs) -> "Issue":
    from app.models import Issue
    return Issue(
        audit_run_id=audit_run.id,
        created_at=datetime.utcnow(),
        **kwargs,
    )


_BLOCK_TITLE_PATTERNS = [
    "access denied", "403 forbidden", "just a moment", "attention required",
    "checking your browser", "please wait", "enable javascript and cookies",
    "ddos protection", "cloudflare", "robot or human", "sorry, you have been blocked",
    "pardon our interruption", "error 403", "error 503", "service unavailable",
    "ip blocked", "security check",
]
_BLOCK_STATUS_CODES = {403, 429, 503, 451}


def _rule_crawler_blocked(audit_run, pages, requests) -> list:
    """Detect when the site is actively blocking the crawler (bot protection / CDN block)."""
    if not pages:
        return []

    blocked_pages = []
    for p in pages:
        is_blocked = False
        reason = None

        # Status code indicates block
        if p.status_code in _BLOCK_STATUS_CODES:
            is_blocked = True
            reason = f"HTTP {p.status_code} response"

        # Page title matches known block page patterns
        title = (p.page_title or "").lower()
        if not is_blocked and any(pat in title for pat in _BLOCK_TITLE_PATTERNS):
            is_blocked = True
            reason = f'Page title "{p.page_title}" matches a bot-block pattern'

        if is_blocked:
            blocked_pages.append((p, reason))

    if not blocked_pages:
        return []

    # Only flag if ALL or most pages are blocked (not just one bad page)
    block_ratio = len(blocked_pages) / len(pages)
    if block_ratio < 0.5 and len(blocked_pages) < 3:
        return []

    sample_page, sample_reason = blocked_pages[0]
    blocked_urls = [p.url for p, _ in blocked_pages[:5]]

    return [_make_issue(
        audit_run,
        severity="critical",
        category="crawler_blocked",
        title="Crawler is being blocked by the site's bot protection",
        description=(
            f"The crawler was blocked on {len(blocked_pages)} of {len(pages)} page(s). "
            f"The site is actively rejecting automated browser traffic — audit results will be "
            f"incomplete or empty. Detection reason: {sample_reason}."
        ),
        evidence_refs=[{
            "blocked_pages": len(blocked_pages),
            "total_pages": len(pages),
            "sample_reason": sample_reason,
            "blocked_urls": blocked_urls,
            "note": (
                "Bot protection systems (Akamai, Cloudflare, PerimeterX, Datadome) detect "
                "headless browsers via TLS fingerprint, IP reputation, missing browser APIs, "
                "or behavioural signals. The mitmproxy component used for network capture has "
                "a distinctive TLS fingerprint that Akamai-protected sites detect at the CDN layer "
                "before JavaScript even runs."
            ),
        }],
        likely_cause=(
            "The site uses an enterprise bot protection service (most likely Akamai Bot Manager "
            "or Cloudflare Bot Management) that identifies headless Chromium via its TLS fingerprint "
            "or HTTP/2 header ordering. The mitmproxy proxy used for traffic capture amplifies this "
            "signal. IP reputation may also be a factor if running from a datacenter/cloud IP."
        ),
        recommendation=(
            "To audit this site: (1) Try the 'logged-in user' mode — inject a real browser session "
            "cookie exported from your own Chrome session, which proves human prior activity; "
            "(2) Run the audit from a residential IP rather than a cloud/home router if using a VPS; "
            "(3) For sites with Cloudflare, a Cloudflare-aware proxy or the site owner's API access "
            "may be needed; (4) Contact the site owner and request audit access with IP allowlisting."
        ),
    )]


def _rule_no_tracking_detected(audit_run, pages, vendors) -> list:
    """Flag when no tracking technology is detected after crawling real pages."""
    if not pages:
        return []
    # Only flag if we actually crawled some pages successfully
    successful_pages = [p for p in pages if not p.error_message]
    if not successful_pages:
        return []
    if vendors:
        return []

    return [_make_issue(
        audit_run,
        severity="critical",
        category="no_tracking",
        title="No tracking technology detected on any crawled page",
        description=(
            f"After successfully crawling {len(successful_pages)} page(s), no tracking vendors, "
            f"analytics tools, tag managers, or pixels were detected. For a site that should have "
            f"tracking in place, this is a critical gap — data collection may be completely absent."
        ),
        evidence_refs=[{
            "pages_crawled": len(successful_pages),
            "vendors_detected": 0,
            "note": (
                "No domain, script src, window global, or cookie matched any known vendor signature. "
                "Checked for: GA4, GTM, Adobe Analytics/Launch, Tealium, Segment, Meta Pixel, "
                "and 15+ other common tracking platforms."
            ),
        }],
        likely_cause=(
            "The site may have no tracking implementation at all, tracking may require user "
            "consent before firing (check with 'accept_consent' mode), all tags may be "
            "server-side only, or an ad-blocker/CSP in the crawl environment is suppressing requests."
        ),
        recommendation=(
            "Run the audit again with 'Accept Consent' mode to rule out consent-gated tracking. "
            "Manually browse the site in Chrome DevTools Network tab and filter by tracking domains. "
            "If no tracking is expected, document this as intentional. "
            "If tracking is expected, verify tag manager installation and container publishing."
        ),
    )]


def _rule_broken_tracking_request(audit_run, pages, requests, vendors) -> list:
    """Flag 4xx/5xx responses for tracking-related requests."""
    issues = []
    vendor_map = {v.vendor_key: v for v in vendors}

    seen_urls = set()
    for req in requests:
        if not req.is_tracking_related:
            continue
        if req.failed or (req.status_code and req.status_code >= 400):
            # Deduplicate by URL
            url_key = req.url[:150]
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)

            status_str = str(req.status_code) if req.status_code else "failed"
            issues.append(_make_issue(
                audit_run,
                page_visit_id=req.page_visit_id,
                severity="high",
                category="broken_tracking",
                title=f"Broken tracking request ({status_str})",
                description=f"A tracking network request returned a {status_str} response: {req.url[:200]}",
                affected_url=req.url[:500],
                evidence_refs=[{"url": req.url[:300], "status": status_str, "method": req.method}],
                likely_cause="The tracking endpoint may be misconfigured, blocked, or the tracking tag is sending incorrect parameters.",
                recommendation="Check the tracking tag configuration and verify the endpoint is reachable. Review any content-security-policy or ad-blocker rules.",
            ))
            if len(issues) >= 20:
                break

    return issues


def _rule_failed_script_load(audit_run, pages, requests, vendors) -> list:
    """Flag failed network requests for .js resources with tracking domains."""
    issues = []
    seen = set()

    for req in requests:
        if not req.failed:
            continue
        url = req.url
        if not (url.endswith(".js") or ".js?" in url or "script" in (req.resource_type or "")):
            continue
        if not req.is_tracking_related:
            continue
        key = url[:150]
        if key in seen:
            continue
        seen.add(key)

        issues.append(_make_issue(
            audit_run,
            page_visit_id=req.page_visit_id,
            severity="critical",
            category="script_error",
            title=f"Tracking script failed to load",
            description=f"A tracking JavaScript resource failed to load: {url[:200]}",
            affected_url=url[:500],
            evidence_refs=[{"url": url[:300], "failure_reason": req.failure_reason or "unknown", "resource_type": req.resource_type}],
            likely_cause="The script may have been blocked by an ad-blocker, firewall, or the URL may be incorrect.",
            recommendation="Verify the script URL is correct, test from a clean browser session, and review network/CSP policies.",
        ))
        if len(issues) >= 10:
            break

    return issues


def _rule_console_js_errors(audit_run, pages, console_events) -> list:
    """Flag pages with significant JavaScript console errors."""
    issues = []
    error_events = [e for e in console_events if e.level == "error"]

    # Group by page
    page_errors: Dict[str, list] = defaultdict(list)
    for e in error_events:
        page_errors[str(e.page_visit_id)].append(e)

    for page_id, events in page_errors.items():
        if len(events) >= 3:
            severity = "high" if len(events) >= 5 else "medium"
            sample = events[:3]
            issues.append(_make_issue(
                audit_run,
                page_visit_id=events[0].page_visit_id,
                severity=severity,
                category="script_error",
                title=f"Multiple JS errors on page ({len(events)} errors)",
                description=f"This page generated {len(events)} JavaScript console errors, which may indicate broken tracking implementations.",
                evidence_refs=[{"level": e.level, "message": e.message[:200], "source": e.source_url} for e in sample],
                likely_cause="JavaScript errors can prevent tracking tags from initializing or firing correctly.",
                recommendation="Investigate the console errors listed in the evidence. Fix any tracking-related script errors first.",
            ))

    return issues


def _rule_missing_expected_vendor(audit_run, config, vendors) -> list:
    """Flag if expected vendors are not detected on any page."""
    if not config or not config.expected_vendors:
        return []

    issues = []
    detected_keys = {v.vendor_key for v in vendors}

    for expected_key in config.expected_vendors:
        if expected_key not in detected_keys:
            issues.append(_make_issue(
                audit_run,
                severity="high",
                category="missing_vendor",
                title=f"Expected vendor not detected: {expected_key}",
                description=f"The vendor '{expected_key}' was configured as expected but was not detected on any crawled page.",
                affected_vendor_key=expected_key,
                evidence_refs=[{"expected_vendor": expected_key, "detected_vendors": list(detected_keys)}],
                likely_cause="The vendor may not be implemented, may be firing only on specific user interactions, or may be blocked.",
                recommendation=f"Verify that {expected_key} is properly installed and firing on relevant pages. Check tag manager configurations.",
            ))

    return issues


def _rule_inconsistent_vendor_coverage(audit_run, pages, page_vendors) -> list:
    """Flag vendors found on some pages in same group but not others."""
    issues = []

    # Group pages by page_group
    group_pages: Dict[str, list] = defaultdict(list)
    for p in pages:
        if p.page_group:
            group_pages[p.page_group].append(p)

    # Get vendor keys per page
    page_vendor_map: Dict[str, set] = defaultdict(set)
    for pv in page_vendors:
        page_vendor_map[str(pv.page_visit_id)].add(pv.vendor_key)

    for group, group_page_list in group_pages.items():
        if len(group_page_list) < 2:
            continue

        # Find vendors present on some pages but not all
        all_vendor_sets = [page_vendor_map.get(str(p.id), set()) for p in group_page_list]
        all_vendors_in_group = set().union(*all_vendor_sets)

        for vendor_key in all_vendors_in_group:
            pages_with = sum(1 for vs in all_vendor_sets if vendor_key in vs)
            pages_without = len(group_page_list) - pages_with

            coverage_pct = pages_with / len(group_page_list)

            # Flag if coverage is between 20% and 80% (inconsistent)
            if 0.2 < coverage_pct < 0.8 and pages_without >= 1:
                issues.append(_make_issue(
                    audit_run,
                    severity="medium",
                    category="coverage_gap",
                    title=f"Inconsistent vendor coverage in '{group}': {vendor_key}",
                    description=(
                        f"Vendor '{vendor_key}' is detected on {pages_with}/{len(group_page_list)} pages "
                        f"in the '{group}' template group. This suggests inconsistent implementation."
                    ),
                    affected_vendor_key=vendor_key,
                    evidence_refs=[{
                        "group": group,
                        "pages_with_vendor": pages_with,
                        "total_pages_in_group": len(group_page_list),
                        "coverage_pct": round(coverage_pct * 100),
                    }],
                    likely_cause="The vendor tag may be missing from some page templates or conditionally suppressed.",
                    recommendation=f"Audit all templates in the '{group}' group and ensure '{vendor_key}' fires consistently.",
                ))

        if len(issues) >= 15:
            break

    return issues


def _rule_duplicate_pageview_signal(audit_run, pages, requests, page_vendors) -> list:
    """Flag duplicate pageview signals from the same vendor on the same page."""
    issues = []

    # For each page, check if the same tracking URL pattern fires multiple times
    page_req_map: Dict[str, list] = defaultdict(list)
    for req in requests:
        if req.is_tracking_related:
            page_req_map[str(req.page_visit_id)].append(req)

    for page_id, page_reqs in page_req_map.items():
        # Group by likely vendor domain (first 50 chars of url as proxy)
        domain_counts: Dict[str, int] = defaultdict(int)
        domain_urls: Dict[str, list] = defaultdict(list)

        for req in page_reqs:
            from urllib.parse import urlparse
            try:
                domain = urlparse(req.url).netloc
            except Exception:
                domain = req.url[:30]
            domain_counts[domain] += 1
            domain_urls[domain].append(req.url[:200])

        for domain, count in domain_counts.items():
            if count >= 3:
                issues.append(_make_issue(
                    audit_run,
                    page_visit_id=next(
                        (r.page_visit_id for r in page_reqs if domain in r.url), None
                    ),
                    severity="medium",
                    category="duplicate_signal",
                    title=f"Possible duplicate tracking signals to {domain}",
                    description=(
                        f"Found {count} requests to '{domain}' on a single page, "
                        f"suggesting duplicate pageview or event signals."
                    ),
                    evidence_refs=[{"domain": domain, "count": count, "sample_urls": domain_urls[domain][:3]}],
                    likely_cause="Duplicate tag firing due to multiple tag manager rules, incorrect event listeners, or tag not deduplicating.",
                    recommendation="Review the tag manager rules for this domain and add deduplication logic to prevent double-counting.",
                ))

    return issues[:10]


def _rule_consent_issue_no_interaction(audit_run, config, pages, page_vendors) -> list:
    """Flag when tracking vendors load with no consent interaction on pages."""
    if not config or config.consent_behavior != "no_interaction":
        return []

    issues = []

    # Find pages where a consent vendor AND a tracking vendor are both present
    page_vendor_map: Dict[str, set] = defaultdict(set)
    page_vendor_categories: Dict[str, set] = defaultdict(set)

    for pv in page_vendors:
        page_vendor_map[str(pv.page_visit_id)].add(pv.vendor_key)
        page_vendor_categories[str(pv.page_visit_id)].add(pv.category)

    consent_vendor_keys = {"onetrust", "cookiebot", "trustarc"}

    for page_id, vendor_keys in page_vendor_map.items():
        has_consent_manager = bool(vendor_keys & consent_vendor_keys)
        has_tracking_vendor = bool(page_vendor_categories.get(page_id, set()) & TRACKING_CATEGORIES - {"consent"})

        if has_consent_manager and has_tracking_vendor:
            tracking_vendors = [
                k for k in vendor_keys
                if k not in consent_vendor_keys
            ]
            issues.append(_make_issue(
                audit_run,
                page_visit_id=next(
                    (pv.page_visit_id for pv in page_vendors if str(pv.page_visit_id) == page_id),
                    None
                ),
                severity="high",
                category="consent",
                title="Tracking vendors fire without consent interaction",
                description=(
                    f"A consent management platform is present, but tracking vendors "
                    f"({', '.join(tracking_vendors[:5])}) appear to fire before any consent "
                    f"interaction (no_interaction mode)."
                ),
                evidence_refs=[{
                    "consent_vendors": list(vendor_keys & consent_vendor_keys),
                    "tracking_vendors_firing": tracking_vendors[:10],
                }],
                likely_cause="The CMP may not be blocking tracking until consent is given, or the implementation does not respect consent signals.",
                recommendation="Verify CMP configuration ensures tracking tags are blocked until explicit consent is granted. Test with consent in all deny states.",
            ))

        if len(issues) >= 10:
            break

    return issues


def _rule_ab_vendor_broken(audit_run, pages, requests, vendors) -> list:
    """Flag A/B testing vendors where associated requests are failing."""
    issues = []

    ab_vendors = [v for v in vendors if v.category in AB_TESTING_CATEGORIES]
    if not ab_vendors:
        return []

    # Group failed requests by vendor domain
    from worker.detectors.vendor_detector import get_signatures
    sigs = {s.key: s for s in get_signatures()}

    for vendor in ab_vendors:
        sig = sigs.get(vendor.vendor_key)
        if not sig:
            continue

        vendor_failed = [
            r for r in requests
            if r.failed and any(d in r.url for d in sig.domains)
        ]
        vendor_total = [
            r for r in requests
            if any(d in r.url for d in sig.domains)
        ]

        if vendor_total and len(vendor_failed) / len(vendor_total) > 0.5:
            issues.append(_make_issue(
                audit_run,
                severity="high",
                category="broken_tracking",
                title=f"A/B testing vendor has high failure rate: {vendor.vendor_name}",
                description=(
                    f"{vendor.vendor_name} requests are failing at a high rate "
                    f"({len(vendor_failed)}/{len(vendor_total)}). A/B test assignments may be broken."
                ),
                affected_vendor_key=vendor.vendor_key,
                evidence_refs=[{"failed_requests": len(vendor_failed), "total_requests": len(vendor_total)}],
                likely_cause="The A/B testing service may be unreachable or the configuration token may be invalid.",
                recommendation=f"Check {vendor.vendor_name} account configuration and network connectivity to their endpoints.",
            ))

    return issues


def _rule_redirect_tracking_loss(audit_run, pages, page_vendors) -> list:
    """Flag pages with redirects where tracking may be lost."""
    issues = []

    pages_with_redirects = [p for p in pages if p.redirect_chain and len(p.redirect_chain) > 0]

    # Pages that had redirects: check if their final URL differs significantly
    page_vendor_map: Dict[str, set] = defaultdict(set)
    for pv in page_vendors:
        page_vendor_map[str(pv.page_visit_id)].add(pv.vendor_key)

    for page in pages_with_redirects:
        vendors_on_page = page_vendor_map.get(str(page.id), set())
        if vendors_on_page and page.url != page.final_url:
            issues.append(_make_issue(
                audit_run,
                page_visit_id=page.id,
                severity="low",
                category="coverage_gap",
                title=f"Redirect may cause tracking data loss",
                description=(
                    f"Page '{page.url}' redirected to '{page.final_url}'. "
                    f"Tracking vendors ({', '.join(list(vendors_on_page)[:3])}) are present on the final page "
                    f"but may miss the original URL in their data."
                ),
                affected_url=page.url,
                evidence_refs=[{
                    "original_url": page.url,
                    "final_url": page.final_url,
                    "vendors_present": list(vendors_on_page),
                }],
                likely_cause="Redirects can strip referrer and campaign parameters, causing analytics to miss attribution.",
                recommendation="Ensure UTM parameters are preserved through redirects, and verify analytics captures the correct page URL.",
            ))

        if len(issues) >= 5:
            break

    return issues


def _rule_network_request_destinations(audit_run, pages, requests, vendors) -> list:
    """Audit every third-party domain receiving data — what is being sent where."""
    from urllib.parse import urlparse
    import json

    if not requests:
        return []

    try:
        base_domain = urlparse(audit_run.base_url).netloc
    except Exception:
        base_domain = ""

    # Build vendor domain lookup
    vendor_domain_map: Dict[str, str] = {}
    try:
        from worker.detectors.vendor_detector import get_signatures
        for sig in get_signatures():
            for d in sig.domains:
                vendor_domain_map[d] = sig.name
    except Exception:
        pass

    # Aggregate per third-party domain
    domain_data: Dict[str, Dict] = {}
    for req in requests:
        try:
            netloc = urlparse(req.url).netloc
        except Exception:
            continue
        if not netloc or netloc == base_domain or netloc.endswith("." + base_domain):
            continue

        if netloc not in domain_data:
            domain_data[netloc] = {
                "count": 0,
                "post_count": 0,
                "pages": set(),
                "sample_urls": [],
                "sample_payloads": [],
                "vendor_name": None,
            }

        entry = domain_data[netloc]
        entry["count"] += 1
        if req.page_visit_id:
            entry["pages"].add(str(req.page_visit_id))
        if len(entry["sample_urls"]) < 3:
            entry["sample_urls"].append(req.url[:200])

        if req.method == "POST" and req.post_data:
            entry["post_count"] += 1
            if len(entry["sample_payloads"]) < 2:
                entry["sample_payloads"].append(req.post_data[:400])

        # Match vendor name
        if entry["vendor_name"] is None:
            for domain_key, vname in vendor_domain_map.items():
                if domain_key in netloc:
                    entry["vendor_name"] = vname
                    break

    issues = []
    # Only flag UNKNOWN domains receiving POST data — known vendors are already in the Vendors tab.
    # Flagging analytics.google.com as a "medium issue" when GA4 is intentionally installed is noise.
    for netloc, data in sorted(domain_data.items(), key=lambda x: -x[1]["post_count"]):
        is_unknown = data["vendor_name"] is None
        if not is_unknown:
            continue  # Known vendor — covered by vendor detection, not an issue
        if data["post_count"] == 0:
            continue  # Only flag unknowns that are actively receiving data

        severity = "high" if data["post_count"] >= 3 else "medium"

        issues.append(_make_issue(
            audit_run,
            severity=severity,
            category="data_destination",
            title=f"Unrecognised domain receiving POST data: {netloc}",
            description=(
                f"WHERE: {netloc}\n"
                f"WHAT: {data['post_count']} POST request(s), {data['count']} total requests\n"
                f"WHO: Not in vendor registry — identity unknown\n"
                f"PAGES: Seen on {len(data['pages'])} page(s)\n"
                f"SAMPLE URL: {data['sample_urls'][0] if data['sample_urls'] else 'N/A'}"
                + (f"\nPAYLOAD SAMPLE: {data['sample_payloads'][0][:300]}" if data["sample_payloads"] else "")
            ),
            evidence_refs=[{
                "domain": netloc,
                "total_requests": data["count"],
                "post_requests": data["post_count"],
                "pages_seen": len(data["pages"]),
                "sample_urls": data["sample_urls"],
                "sample_payloads": data["sample_payloads"],
            }],
            likely_cause=(
                "An unrecognised script or tag is sending data to this domain. "
                "May be a custom endpoint, a vendor not yet in the registry, or an unauthorised tracker."
            ),
            recommendation=(
                "Identify what script is making requests to this domain (check the Network tab in DevTools). "
                "Review the POST payload for personal data. If it's a legitimate vendor, add it to the registry. "
                "If unknown, escalate to the client for confirmation before the next audit."
            ),
        ))

        if len(issues) >= 15:
            break

    return issues


def _rule_data_layer_audit(audit_run, pages) -> list:
    """Document data layer contents — dataLayer, utag_data, digitalData, _satellite."""
    import json

    if not pages:
        return []

    issues = []
    PII_HINT_KEYS = {
        "email", "mail", "user_id", "userId", "user_email", "userEmail",
        "customer_id", "customerId", "phone", "firstname", "lastname",
        "first_name", "last_name", "name", "username", "user_name",
        "address", "zip", "postcode", "dob", "date_of_birth",
    }

    # Aggregate data layer variables across all pages
    dl_keys_seen: Dict[str, set] = {}  # key -> set of page urls
    utag_keys_seen: Dict[str, set] = {}
    digital_data_keys_seen: Dict[str, set] = {}
    satellite_props: Dict[str, set] = {}

    for page in pages:
        if not page.data_layer:  # type: ignore
            continue
        dl = page.data_layer
        page_url = page.url or ""

        # dataLayer events
        if "dataLayer" in dl and isinstance(dl["dataLayer"], list):
            for event in dl["dataLayer"]:
                if isinstance(event, dict):
                    for k in event.keys():
                        dl_keys_seen.setdefault(k, set()).add(page_url)

        # utag_data
        if "utag_data" in dl and isinstance(dl["utag_data"], dict):
            for k in dl["utag_data"].keys():
                utag_keys_seen.setdefault(k, set()).add(page_url)

        # digitalData
        if "digitalData" in dl and isinstance(dl["digitalData"], dict):
            for k in dl["digitalData"].keys():
                digital_data_keys_seen.setdefault(k, set()).add(page_url)

        # _satellite (Adobe Launch)
        if "_satellite" in dl and isinstance(dl["_satellite"], dict):
            for k, v in dl["_satellite"].items():
                satellite_props.setdefault(k, set()).add(str(v)[:100] if v else "")

    # Only create findings when there's actual PII risk in data layers.
    # "dataLayer has 12 variables" with no PII is not an issue — it's expected.
    # The AI summary already reports data layer inventory for discovery/inheritance audits.

    for layer_name, keys_seen, layer_label, cause, rec_base in [
        ("dataLayer", dl_keys_seen, "Google Tag Manager dataLayer",
         "GTM dataLayer is populated by the site's tag implementation.",
         "Ensure no raw personal data is pushed to the dataLayer without consent."),
        ("utag_data", utag_keys_seen, "Tealium utag_data",
         "Tealium Universal Data Object (UDO) is populated on page load.",
         "Audit PII keys in utag_data per your data governance policy."),
        ("digitalData", digital_data_keys_seen, "W3C digitalData layer",
         "A W3C-standard digitalData layer is present.",
         "Ensure PII values are not exposed in the digitalData object without consent."),
    ]:
        if not keys_seen:
            continue
        pii_keys = [k for k in keys_seen if k.lower() in PII_HINT_KEYS]
        if not pii_keys:
            continue  # No PII risk — not worth an issue, inventory is in the summary

        issues.append(_make_issue(
            audit_run,
            severity="high",
            category="data_layer",
            title=f"Possible PII in {layer_label}: {', '.join(pii_keys[:5])}",
            description=(
                f"WHERE: window.{layer_name}\n"
                f"WHAT: {layer_label} contains keys that suggest personal data\n"
                f"⚠ SUSPECT KEYS: {', '.join(pii_keys)}\n"
                f"ALL VARIABLES ({len(keys_seen)}): {', '.join(sorted(keys_seen.keys())[:30])}"
            ),
            evidence_refs=[{
                "layer": layer_name,
                "pii_hint_keys": pii_keys,
                "all_variables": sorted(keys_seen.keys())[:50],
                "pages_seen": list({url for urls in keys_seen.values() for url in urls})[:5],
            }],
            likely_cause=cause,
            recommendation=f"{rec_base} Confirm each PII key is hashed or pseudonymised before being pushed.",
        ))

    # _satellite: only flag if property ID is unexpected (always include as evidence though)
    if satellite_props:
        prop_id = next(iter(satellite_props.get("property", set())), None)
        build_info = next(iter(satellite_props.get("buildInfo", set())), None)
        # Always create — Adobe Launch property ID is critical audit info for inherited clients
        issues.append(_make_issue(
            audit_run,
            severity="low",
            category="data_layer",
            title=f"Adobe Launch property detected" + (f": {prop_id}" if prop_id else ""),
            description=(
                f"WHERE: window._satellite (Adobe Experience Platform Tags)\n"
                f"WHAT: Adobe Launch runtime is active on this site\n"
                + (f"PROPERTY ID: {prop_id}\n" if prop_id else "Property ID not exposed\n")
                + (f"BUILD INFO: {build_info}\n" if build_info else "")
                + f"WHY THIS MATTERS: Confirms which Adobe Launch property/environment is publishing rules to this site."
            ),
            evidence_refs=[{
                "layer": "_satellite",
                "property_id": prop_id,
                "build_info": build_info,
                "runtime_keys": sorted(satellite_props.keys())[:20],
            }],
            likely_cause="Adobe Experience Platform Tags is the tag management system in use.",
            recommendation=(
                "Verify the property ID matches the expected Adobe Launch property for this environment "
                "(prod vs staging). Mismatched property IDs indicate the wrong container is published."
            ),
        ))

    return issues


def _rule_template_inconsistency(audit_run, pages, page_vendors) -> list:
    """Flag page groups where vendor coverage differs from the group average."""
    issues = []

    group_pages: Dict[str, list] = defaultdict(list)
    for p in pages:
        if p.page_group:
            group_pages[p.page_group].append(p)

    page_vendor_map: Dict[str, set] = defaultdict(set)
    for pv in page_vendors:
        page_vendor_map[str(pv.page_visit_id)].add(pv.vendor_key)

    for group, group_page_list in group_pages.items():
        if len(group_page_list) < 3:
            continue

        # Count unique vendor sets
        vendor_sets = [frozenset(page_vendor_map.get(str(p.id), set())) for p in group_page_list]
        unique_sets = set(vendor_sets)

        if len(unique_sets) > 1:
            most_common = max(unique_sets, key=lambda s: vendor_sets.count(s))
            outliers = [
                group_page_list[i] for i, vs in enumerate(vendor_sets)
                if vs != most_common
            ]

            if outliers and len(outliers) < len(group_page_list):
                issues.append(_make_issue(
                    audit_run,
                    severity="medium",
                    category="coverage_gap",
                    title=f"Template inconsistency in '{group}': {len(outliers)} page(s) differ",
                    description=(
                        f"{len(outliers)} page(s) in the '{group}' group have a different vendor set "
                        f"than the majority ({len(group_page_list) - len(outliers)} pages)."
                    ),
                    evidence_refs=[{
                        "group": group,
                        "outlier_urls": [p.url for p in outliers[:3]],
                        "expected_vendor_set": list(most_common),
                    }],
                    likely_cause="Template variations or conditional logic may cause some pages to have different tracking configurations.",
                    recommendation=f"Review the outlier pages in the '{group}' group and standardize their tracking implementation.",
                ))

        if len(issues) >= 5:
            break

    return issues
