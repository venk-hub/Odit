"""
Pure-Python computation helpers for audit summary metrics.
Used by both app/web/routes.py (async, UI) and worker/exports/ (sync, reports).
No DB calls — callers load ORM objects and pass them in.
"""
from datetime import datetime, timezone
from collections import defaultdict
from typing import List, Dict, Any
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Cookie classification
# ---------------------------------------------------------------------------
KNOWN_COOKIES: Dict[str, tuple] = {
    "_ga":               ("Google Analytics", "analytics",  "GA4/UA visitor identifier — 2 year expiry"),
    "_gid":              ("Google Analytics", "analytics",  "GA daily session identifier — 24 hour expiry"),
    "_gat":              ("Google Analytics", "analytics",  "GA request throttle — 1 minute expiry"),
    "_gat_gtag":         ("Google Analytics", "analytics",  "GA4 request throttle — 1 minute expiry"),
    "_gcl_au":           ("Google Ads",       "marketing",  "Google Ads conversion linker — 90 day expiry"),
    "_gcl_aw":           ("Google Ads",       "marketing",  "Google Ads click ID — 90 day expiry"),
    "_gcl_dc":           ("Google Ads",       "marketing",  "Google Ads cross-channel — 90 day expiry"),
    "IDE":               ("Google DoubleClick","marketing", "Google Display & Video advertising"),
    "DSID":              ("Google DoubleClick","marketing", "Google DoubleClick user identifier"),
    "_gac_":             ("Google Ads",       "marketing",  "Google Ads campaign — 90 day expiry"),
    "_fbp":              ("Meta Pixel",       "marketing",  "Facebook advertising pixel — 90 day expiry"),
    "_fbc":              ("Meta Pixel",       "marketing",  "Facebook click ID — 90 day expiry"),
    "fr":                ("Meta",             "marketing",  "Facebook advertising and analytics"),
    "datr":              ("Meta",             "marketing",  "Facebook browser identifier"),
    "sb":                ("Meta",             "marketing",  "Facebook browser identifier"),
    "_ttp":              ("TikTok Pixel",     "marketing",  "TikTok advertising pixel — 13 month expiry"),
    "_tt_enable_cookie": ("TikTok",           "marketing",  "TikTok cookie consent flag"),
    "tt_sessionid":      ("TikTok",           "marketing",  "TikTok session identifier"),
    "_uetsid":           ("Microsoft UET",    "marketing",  "Microsoft advertising session — 1 day"),
    "_uetvid":           ("Microsoft UET",    "marketing",  "Microsoft advertising visitor — 16 day"),
    "MUID":              ("Microsoft",        "marketing",  "Microsoft user identifier — 1 year"),
    "MR":                ("Microsoft",        "marketing",  "Microsoft redirect helper — 7 day"),
    "ANONCHK":           ("Microsoft",        "marketing",  "Microsoft session check — 10 min"),
    "_hjid":             ("Hotjar",           "analytics",  "Hotjar visitor identifier — 1 year"),
    "_hjTLDTest":        ("Hotjar",           "analytics",  "Hotjar TLD detection — session"),
    "_hjFirstSeen":      ("Hotjar",           "analytics",  "Hotjar new visitor flag — session"),
    "_hjIncludedInPageviewSample": ("Hotjar", "analytics",  "Hotjar sampling flag — session"),
    "_hjAbsoluteSessionInProgress": ("Hotjar","analytics",  "Hotjar active session — session"),
    "ajs_user_id":       ("Segment",          "analytics",  "Segment identified user"),
    "ajs_anonymous_id":  ("Segment",          "analytics",  "Segment anonymous visitor — 1 year"),
    "mp_optout":         ("Mixpanel",         "analytics",  "Mixpanel opt-out flag"),
    "intercom-id":       ("Intercom",         "functional", "Intercom visitor identifier — 9 month"),
    "intercom-session":  ("Intercom",         "functional", "Intercom session — 1 week"),
    "__stripe_mid":      ("Stripe",           "functional", "Stripe fraud prevention — 1 year"),
    "__stripe_sid":      ("Stripe",           "functional", "Stripe session — 30 min"),
    "OptanonConsent":              ("OneTrust", "consent",  "OneTrust consent preferences — 1 year"),
    "OptanonAlertBoxClosed":       ("OneTrust", "consent",  "OneTrust banner dismissed flag — 1 year"),
    "eupubconsent-v2":             ("OneTrust", "consent",  "IAB TCF consent string"),
    "CookieConsent":     ("Cookiebot",        "consent",   "Cookiebot consent preferences — 1 year"),
    "cf_clearance":      ("Cloudflare",       "security",  "Cloudflare challenge clearance — 30 min"),
    "__cf_bm":           ("Cloudflare",       "security",  "Cloudflare bot management — 30 min"),
    "__cfduid":          ("Cloudflare",       "security",  "Cloudflare visitor identifier (deprecated)"),
    "PHPSESSID":         (None,               "functional", "PHP session identifier — session"),
    "JSESSIONID":        (None,               "functional", "Java/Tomcat session identifier — session"),
    "ASP.NET_SessionId": (None,               "functional", ".NET session identifier — session"),
    "session":           (None,               "functional", "Application session identifier"),
    "session_id":        (None,               "functional", "Application session identifier"),
    "sessionid":         (None,               "functional", "Application session identifier"),
    "_session_id":       (None,               "functional", "Application session identifier"),
    "_csrf":             (None,               "security",  "Cross-site request forgery protection"),
    "csrf_token":        (None,               "security",  "Cross-site request forgery protection"),
    "csrftoken":         (None,               "security",  "Cross-site request forgery protection"),
    "euconsent-v2":      (None,               "consent",   "IAB TCF v2 consent string"),
}

KNOWN_PREFIXES: List[tuple] = [
    ("_ga_",             "Google Analytics 4", "analytics",  "GA4 measurement ID tracker"),
    ("_gat_",            "Google Analytics",   "analytics",  "GA request throttle"),
    ("_gac_",            "Google Ads",         "marketing",  "Google Ads campaign parameter"),
    ("_hjSession",       "Hotjar",             "analytics",  "Hotjar session data"),
    ("hjSession",        "Hotjar",             "analytics",  "Hotjar session data"),
    ("_hjSessionUser",   "Hotjar",             "analytics",  "Hotjar user session"),
    ("mp_",              "Mixpanel",           "analytics",  "Mixpanel analytics data"),
    ("_pk_id",           "Matomo",             "analytics",  "Matomo visitor identifier"),
    ("_pk_ses",          "Matomo",             "analytics",  "Matomo session"),
    ("ajs_",             "Segment",            "analytics",  "Segment analytics"),
    ("fbm_",             "Meta",               "marketing",  "Facebook Messenger data"),
    ("fbsr_",            "Meta",               "marketing",  "Facebook signed request"),
    ("_ttp_",            "TikTok Pixel",       "marketing",  "TikTok pixel data"),
    ("intercom-",        "Intercom",           "functional", "Intercom widget data"),
    ("OptanonConsent",   "OneTrust",           "consent",   "OneTrust consent preferences"),
    ("_uet",             "Microsoft UET",      "marketing",  "Microsoft advertising"),
]


def _classify_cookie(name: str) -> tuple:
    if name in KNOWN_COOKIES:
        return KNOWN_COOKIES[name]
    for prefix, vendor, cat, desc in KNOWN_PREFIXES:
        if name.startswith(prefix):
            return (vendor, cat, desc)
    lname = name.lower()
    if any(x in lname for x in ("sess", "session", "sid")):
        return (None, "functional", "Session management cookie")
    if any(x in lname for x in ("csrf", "xsrf", "token")):
        return (None, "security", "Security / anti-forgery token")
    if any(x in lname for x in ("consent", "gdpr", "optout", "opt_out")):
        return (None, "consent", "Consent or opt-out preference")
    if any(x in lname for x in ("cart", "basket", "wishlist", "order")):
        return (None, "functional", "E-commerce / cart data")
    if any(x in lname for x in ("utm_", "gclid", "fbclid", "msclkid", "ttclid")):
        return (None, "marketing", "Attribution / click ID parameter")
    return (None, "unknown", "Unclassified — purpose not determined")


def _extract_base_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().lstrip("www.").split(":")[0]
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return ""


def _parse_expiry(expires) -> str:
    if expires is None or expires == -1 or expires == 0:
        return "Session"
    try:
        exp = float(expires)
        now = datetime.now(timezone.utc).timestamp()
        days = (exp - now) / 86400
        if days < 0:
            return "Expired"
        if days < 1:
            return f"{int(days * 24)}h"
        if days <= 365:
            return f"{int(days)}d"
        return f"{days / 365:.1f}yr"
    except Exception:
        return "Unknown"


# ---------------------------------------------------------------------------
# Cookie Register
# ---------------------------------------------------------------------------

def build_cookie_register(pages) -> List[Dict[str, Any]]:
    register: Dict[tuple, Dict] = {}
    for page in pages:
        if not page.url:
            continue
        base_domain = _extract_base_domain(page.url)
        cookie_list = []
        if page.cookies_detail and isinstance(page.cookies_detail, list):
            cookie_list = page.cookies_detail
        elif page.cookies:
            cookie_list = [{"name": n} for n in page.cookies]

        for cookie in cookie_list:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name", "").strip()
            if not name:
                continue
            raw_domain = cookie.get("domain", "").lstrip(".")
            domain = raw_domain or "unknown"
            key = (name, domain)
            if key not in register:
                vendor, purpose_cat, description = _classify_cookie(name)
                if not raw_domain or not base_domain:
                    party = "unknown"
                else:
                    cookie_base = _extract_base_domain(raw_domain)
                    party = "1st" if (cookie_base == base_domain or base_domain.endswith(cookie_base)) else "3rd"
                register[key] = {
                    "name": name,
                    "domain": domain,
                    "party": party,
                    "expiry": _parse_expiry(cookie.get("expires")),
                    "http_only": cookie.get("httpOnly"),
                    "secure": cookie.get("secure"),
                    "same_site": cookie.get("sameSite", ""),
                    "purpose_category": purpose_cat,
                    "vendor": vendor or "",
                    "description": description,
                    "pages_seen": set(),
                }
            register[key]["pages_seen"].add(page.url)

    result = []
    for record in register.values():
        r = dict(record)
        r["page_count"] = len(r.pop("pages_seen"))
        result.append(r)

    cat_order = {"consent": 0, "functional": 1, "security": 2, "analytics": 3, "marketing": 4, "unknown": 5}
    result.sort(key=lambda x: (cat_order.get(x["purpose_category"], 9), x["party"], x["name"].lower()))
    return result


# ---------------------------------------------------------------------------
# Tag Source Attribution
# ---------------------------------------------------------------------------

# Short display names for TMS vendors used in attribution badges
TMS_DISPLAY_NAMES = {
    "google_tag_manager": "GTM",
    "adobe_launch": "Adobe Launch",
    "tealium": "Tealium",
    "segment": "Segment",
    "ensighten": "Ensighten",
    "signal": "Signal",
}


def _vendor_domains_from_evidence(vendors_for_key) -> List[str]:
    """Extract unique matched_domain values from a vendor's evidence records."""
    domains = set()
    for v in vendors_for_key:
        ev = v.evidence or {}
        d = ev.get("matched_domain")
        if d:
            domains.add(d.lower())
    return list(domains)


def build_tag_attribution(vendors, pages, requests) -> Dict[str, str]:
    all_script_srcs: set = set()
    for page in pages:
        for src in (page.script_srcs or []):
            all_script_srcs.add(src.lower())

    # Group audit-level vendors by key (same vendor key may appear multiple times
    # with different detection methods/evidence)
    from collections import defaultdict
    vendors_by_key: Dict[str, list] = defaultdict(list)
    for v in vendors:
        vendors_by_key[v.vendor_key].append(v)

    # Identify which TMS vendors are present on this site
    vendor_keys = set(vendors_by_key.keys())
    detected_tms = [(vkey, label) for vkey, label in TMS_DISPLAY_NAMES.items() if vkey in vendor_keys]
    tms_label = detected_tms[0][1] if detected_tms else None

    attributions: Dict[str, str] = {}
    for vkey, vlist in vendors_by_key.items():
        # TMS vendors themselves don't get a "via" attribution
        if vkey in TMS_DISPLAY_NAMES:
            continue

        # Use matched_domain values from evidence to find network requests
        vendor_domains = _vendor_domains_from_evidence(vlist)

        found_in_html = any(
            any(domain in src for src in all_script_srcs)
            for domain in vendor_domains
        ) if vendor_domains else False

        vendor_reqs = [
            r for r in requests
            if vendor_domains and any(d in (r.url or "").lower() for d in vendor_domains)
        ]
        has_script_reqs = any(r.resource_type == "script" for r in vendor_reqs)
        has_pixel_reqs = any(r.resource_type == "image" for r in vendor_reqs)
        has_beacon_reqs = any(r.resource_type in ("xhr", "fetch", "ping") for r in vendor_reqs)
        has_only_data_reqs = bool(vendor_reqs) and not has_script_reqs

        if has_script_reqs and tms_label:
            # TMS is present — script-loaded vendors are most likely injected by it
            source = f"Via {tms_label}"
        elif has_script_reqs:
            source = "Direct (HTML tag)"
        elif has_only_data_reqs and has_beacon_reqs:
            # XHR/fetch/ping takes priority over image beacons — indicates a data collection API
            source = "Beacon / API"
        elif has_only_data_reqs and has_pixel_reqs:
            source = "Pixel"
        elif has_only_data_reqs:
            source = "Beacon / API"
        elif vendor_reqs:
            source = "Dynamic injection"
        else:
            source = None

        if source:
            attributions[vkey] = source

    return attributions


# ---------------------------------------------------------------------------
# Performance Impact
# ---------------------------------------------------------------------------

def build_performance_stats(vendors, requests, page_level_vendors) -> List[Dict[str, Any]]:
    pvid_to_key: Dict = {pv.id: pv.vendor_key for pv in page_level_vendors}

    keyed_reqs: Dict[str, List] = defaultdict(list)
    for req in requests:
        if req.vendor_id and req.vendor_id in pvid_to_key:
            keyed_reqs[pvid_to_key[req.vendor_id]].append(req)

    stats = []
    for vendor in vendors:
        reqs = keyed_reqs.get(vendor.vendor_key, [])
        timings = [r.timing_ms for r in reqs if r.timing_ms and r.timing_ms > 0]
        pages_affected = len(set(str(r.page_visit_id) for r in reqs)) if reqs else vendor.page_count or 0
        stats.append({
            "vendor_name": vendor.vendor_name,
            "category": vendor.category,
            "request_count": len(reqs),
            "avg_timing_ms": round(sum(timings) / len(timings), 0) if timings else None,
            "max_timing_ms": round(max(timings), 0) if timings else None,
            "pages_affected": pages_affected,
            "has_data": bool(timings),
        })

    stats.sort(key=lambda x: (-(x["avg_timing_ms"] or 0), x["vendor_name"]))
    return stats


# ---------------------------------------------------------------------------
# Executive Metrics
# ---------------------------------------------------------------------------

def compute_executive_metrics(vendors, issues, config, pages) -> Dict[str, Any]:
    issue_counts = {
        "critical": sum(1 for i in issues if i.severity == "critical"),
        "high":     sum(1 for i in issues if i.severity == "high"),
        "medium":   sum(1 for i in issues if i.severity == "medium"),
        "low":      sum(1 for i in issues if i.severity == "low"),
    }
    risk_score = (
        issue_counts["critical"] * 10 +
        issue_counts["high"] * 5 +
        issue_counts["medium"] * 2 +
        issue_counts["low"] * 1
    )
    if risk_score == 0:
        risk_rating, risk_color = "Low", "#16a34a"
    elif risk_score <= 10:
        risk_rating, risk_color = "Medium", "#ca8a04"
    elif risk_score <= 30:
        risk_rating, risk_color = "High", "#ea580c"
    else:
        risk_rating, risk_color = "Critical", "#dc2626"

    consent_mode = None
    if config:
        cm = config.consent_behavior
        consent_mode = cm.value if hasattr(cm, "value") else str(cm)

    has_consent_issues = any(i.category == "consent" for i in issues)
    has_critical = issue_counts["critical"] > 0
    has_tracking = len(vendors) > 0

    if not has_tracking:
        gdpr_posture = ccpa_posture = "N/A — no tracking detected"
    elif has_consent_issues and has_critical:
        gdpr_posture = "Not Ready — active consent violations detected"
        ccpa_posture = "Not Ready — third-party data sharing without verified opt-out"
    elif has_consent_issues:
        gdpr_posture = "Partial — consent issues present, remediation required"
        ccpa_posture = "Partial — review opt-out mechanism coverage"
    elif consent_mode == "no_interaction":
        gdpr_posture = "Unverified — audit ran without consent interaction"
        ccpa_posture = "Unverified — re-run with accept_consent to confirm gating"
    else:
        gdpr_posture = "Requires Review — tracking present, verify lawful basis per vendor"
        ccpa_posture = "Requires Review — confirm opt-out covers all detected vendors"

    top_issues = sorted(
        [i for i in issues if i.severity in ("critical", "high")],
        key=lambda i: {"critical": 0, "high": 1}.get(i.severity, 2)
    )[:3]

    vendor_categories: Dict[str, int] = defaultdict(int)
    for v in vendors:
        vendor_categories[v.category] += 1

    return {
        "risk_score": risk_score,
        "risk_rating": risk_rating,
        "risk_color": risk_color,
        "gdpr_posture": gdpr_posture,
        "ccpa_posture": ccpa_posture,
        "top_issues": top_issues,
        "issue_counts": issue_counts,
        "total_issues": sum(issue_counts.values()),
        "vendor_count": len(vendors),
        "vendor_categories": dict(vendor_categories),
        "pages_crawled": len(pages),
        "consent_mode": consent_mode or "not_set",
    }
