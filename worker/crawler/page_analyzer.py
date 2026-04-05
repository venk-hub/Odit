"""
Page analyzer: extracts metadata, storage, cookies, scripts from a Playwright page.
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("odit.worker.page_analyzer")


def compute_page_group(url: str) -> str:
    """Group a URL by its first two path segments."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return "/"
    if len(parts) == 1:
        return "/" + parts[0]
    return "/" + "/".join(parts[:2])


def extract_page_metadata(page) -> Dict[str, Any]:
    """Extract title, meta description, canonical from the page."""
    try:
        title = page.title()
    except Exception:
        title = None

    try:
        meta_description = page.evaluate("""
            () => {
                const el = document.querySelector('meta[name="description"]');
                return el ? el.getAttribute('content') : null;
            }
        """)
    except Exception:
        meta_description = None

    try:
        canonical_url = page.evaluate("""
            () => {
                const el = document.querySelector('link[rel="canonical"]');
                return el ? el.getAttribute('href') : null;
            }
        """)
    except Exception:
        canonical_url = None

    return {
        "title": title,
        "meta_description": meta_description,
        "canonical_url": canonical_url,
    }


def extract_storage(page) -> Dict[str, List[str]]:
    """Extract localStorage and sessionStorage keys."""
    try:
        local_keys = page.evaluate("""
            () => {
                try { return Object.keys(localStorage); } catch(e) { return []; }
            }
        """)
    except Exception:
        local_keys = []

    try:
        session_keys = page.evaluate("""
            () => {
                try { return Object.keys(sessionStorage); } catch(e) { return []; }
            }
        """)
    except Exception:
        session_keys = []

    return {"local_storage_keys": local_keys or [], "session_storage_keys": session_keys or []}


def extract_cookies(context) -> List[Dict]:
    """Extract cookies from browser context with full detail."""
    try:
        cookies = context.cookies()
        result = []
        for c in cookies:
            result.append({
                "name": c["name"],
                "value": c.get("value", ""),
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
                "expires": c.get("expires"),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
                "sameSite": c.get("sameSite", ""),
            })
        return result
    except Exception as e:
        logger.warning(f"Failed to extract cookies: {e}")
        return []


def extract_script_srcs(page) -> List[str]:
    """Extract all script src URLs from the page."""
    try:
        srcs = page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[src]');
                return Array.from(scripts).map(s => s.src).filter(Boolean);
            }
        """)
        return srcs or []
    except Exception as e:
        logger.warning(f"Failed to extract script srcs: {e}")
        return []


def extract_window_globals(page) -> List[str]:
    """Detect known analytics/tracking window globals."""
    known_globals = [
        "gtag", "dataLayer", "ga", "google_tag_manager",
        "_satellite", "s_gi", "AppMeasurement", "s",
        "utag", "utag_data",
        "analytics", "rudderanalytics",
        "mixpanel", "amplitude", "heap",
        "fbq", "_fbq",
        "_linkedin_data_partner_ids", "lintrk",
        "ttq",
        "optimizely",
        "VWO",
        "DY",
        "OneTrust", "OnetrustActiveGroups",
        "Cookiebot", "CookieConsent",
        "truste",
        "LDClient",
        "td", "TreasureData",
        "mParticle",
        "Visitor",
        "digitalData",
        "adobeDataLayer",
    ]
    try:
        detected = page.evaluate("""
            (globals) => globals.filter(g => {
                try {
                    const parts = g.split('.');
                    let obj = window;
                    for (const p of parts) {
                        if (obj === undefined || obj === null) return false;
                        obj = obj[p];
                    }
                    return obj !== undefined && obj !== null;
                } catch(e) { return false; }
            })
        """, known_globals)
        return detected or []
    except Exception as e:
        logger.warning(f"Failed to extract window globals: {e}")
        return []


def extract_data_layer(page) -> Dict[str, Any]:
    """Extract common data layer objects: dataLayer, utag_data, digitalData, etc."""
    result = {}

    # Primary: collect from the push-interceptor buffer (catches events fired during load)
    try:
        dl_buf = page.evaluate("""
            () => {
                try {
                    const buf = window.__oditDLBuf;
                    if (Array.isArray(buf) && buf.length > 0) {
                        return buf.map(item => {
                            try { return JSON.parse(JSON.stringify(item)); } catch(e) { return String(item); }
                        });
                    }
                } catch(e) {}
                return null;
            }
        """)
        if dl_buf:
            result["dataLayer"] = dl_buf
    except Exception:
        pass

    # Fallback: snapshot window.dataLayer if the interceptor wasn't in place
    if "dataLayer" not in result:
        try:
            data_layer = page.evaluate("""
                () => {
                    try {
                        const dl = window.dataLayer;
                        if (Array.isArray(dl) && dl.length > 0) {
                            return dl.slice(-10).map(item => {
                                try { return JSON.parse(JSON.stringify(item)); } catch(e) { return String(item); }
                            });
                        }
                    } catch(e) {}
                    return null;
                }
            """)
            if data_layer:
                result["dataLayer"] = data_layer
        except Exception:
            pass

    try:
        utag_data = page.evaluate("""
            () => {
                try {
                    if (window.utag_data && typeof window.utag_data === 'object') {
                        return JSON.parse(JSON.stringify(window.utag_data));
                    }
                } catch(e) {}
                return null;
            }
        """)
        if utag_data:
            result["utag_data"] = utag_data
    except Exception:
        pass

    try:
        digital_data = page.evaluate("""
            () => {
                try {
                    if (window.digitalData && typeof window.digitalData === 'object') {
                        return JSON.parse(JSON.stringify(window.digitalData));
                    }
                } catch(e) {}
                return null;
            }
        """)
        if digital_data:
            result["digitalData"] = digital_data
    except Exception:
        pass

    try:
        adobeDataLayer = page.evaluate("""
            () => {
                try {
                    const dl = window.adobeDataLayer;
                    if (Array.isArray(dl) && dl.length > 0) {
                        return dl.slice(-10).map(item => {
                            try { return JSON.parse(JSON.stringify(item)); } catch(e) { return String(item); }
                        });
                    }
                } catch(e) {}
                return null;
            }
        """)
        if adobeDataLayer:
            result["adobeDataLayer"] = adobeDataLayer
    except Exception:
        pass

    # Adobe Launch (_satellite) runtime details
    try:
        satellite = page.evaluate("""
            () => {
                try {
                    const s = window._satellite;
                    if (!s || typeof s !== 'object') return null;
                    const out = {};
                    try { if (s.property && s.property.id) out.property = s.property.id; } catch(e) {}
                    try { if (s.buildInfo) out.buildInfo = JSON.parse(JSON.stringify(s.buildInfo)); } catch(e) {}
                    try {
                        const rules = s.container && s.container.data && s.container.data.rules;
                        if (Array.isArray(rules)) out.rule_count = rules.length;
                    } catch(e) {}
                    try { if (s.company) out.company = s.company; } catch(e) {}
                    return Object.keys(out).length > 0 ? out : { present: true };
                } catch(e) { return null; }
            }
        """)
        if satellite:
            result["_satellite"] = satellite
    except Exception:
        pass

    # Adobe Analytics s object variables
    try:
        adobe_s = page.evaluate("""
            () => {
                try {
                    const s = window.s;
                    if (!s || typeof s !== 'object' || !s.account) return null;
                    const out = { account: s.account };
                    if (s.pageName) out.pageName = s.pageName;
                    if (s.pageType) out.pageType = s.pageType;
                    if (s.channel) out.channel = s.channel;
                    const evars = {}, props = {};
                    for (let i = 1; i <= 75; i++) {
                        if (s['eVar' + i]) evars['eVar' + i] = String(s['eVar' + i]).substring(0, 100);
                        if (s['prop' + i]) props['prop' + i] = String(s['prop' + i]).substring(0, 100);
                    }
                    if (Object.keys(evars).length) out.evars = evars;
                    if (Object.keys(props).length) out.props = props;
                    return out;
                } catch(e) { return null; }
            }
        """)
        if adobe_s:
            result["adobe_s"] = adobe_s
    except Exception:
        pass

    return result


def take_screenshot(page, output_path: str) -> Optional[str]:
    """Take a full-page screenshot and save to output_path."""
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        page.screenshot(path=output_path, full_page=True, timeout=15000)
        return output_path
    except Exception as e:
        logger.warning(f"Screenshot failed: {e}")
        return None


def extract_service_workers(page) -> List[Dict]:
    """Detect registered service worker script URLs."""
    try:
        result = page.evaluate("""
            async () => {
                if (!navigator.serviceWorker) return [];
                try {
                    const regs = await navigator.serviceWorker.getRegistrations();
                    return regs.map(r => ({
                        scope: r.scope,
                        script_url: (r.active || r.installing || r.waiting || {}).scriptURL || null,
                        state: r.active ? 'active' : r.installing ? 'installing' : 'waiting',
                    }));
                } catch(e) { return []; }
            }
        """)
        return result or []
    except Exception as e:
        logger.warning(f"Failed to extract service workers: {e}")
        return []


def extract_iframe_signals(page) -> Dict[str, List]:
    """
    Extract script srcs and window globals from iframes.
    Playwright's 'response' event already captures iframe network requests,
    so this adds DOM-level signals (loaded scripts, globals) from child frames.
    """
    IFRAME_GLOBALS = [
        "gtag", "dataLayer", "ga", "google_tag_manager",
        "_satellite", "analytics", "rudderanalytics",
        "mixpanel", "amplitude", "heap",
        "fbq", "ttq", "optimizely", "VWO", "DY",
        "OneTrust", "Cookiebot", "utag",
    ]
    iframe_urls: List[str] = []
    extra_script_srcs: List[str] = []
    extra_globals: List[str] = []

    for frame in page.frames[1:]:  # index 0 is the main frame
        try:
            url = frame.url
            if url and url not in ("about:blank", "", "null"):
                iframe_urls.append(url)
        except Exception:
            pass

        try:
            srcs = frame.evaluate(
                "() => Array.from(document.querySelectorAll('script[src]')).map(s => s.src).filter(Boolean)"
            )
            if srcs:
                extra_script_srcs.extend(srcs)
        except Exception:
            pass

        try:
            found = frame.evaluate(
                "(globals) => globals.filter(g => { "
                "try { return window[g] !== undefined && window[g] !== null; } "
                "catch(e) { return false; } })",
                IFRAME_GLOBALS,
            )
            if found:
                extra_globals.extend(found)
        except Exception:
            pass

    return {
        "iframe_urls": list(dict.fromkeys(iframe_urls)),           # deduped, order-preserved
        "extra_script_srcs": list(dict.fromkeys(extra_script_srcs)),
        "extra_globals": list(dict.fromkeys(extra_globals)),
    }


def extract_links(page, base_domain: str, allowed_domains: list = None) -> List[str]:
    """Extract all internal links from the page."""
    from urllib.parse import urlparse, urljoin
    # Build the full set of accepted domains: explicit list + www/non-www variants
    if allowed_domains:
        accepted = set(allowed_domains)
    else:
        accepted = {base_domain}
    # Always include the www/non-www counterpart so redirects don't break BFS
    for d in list(accepted):
        if d.startswith("www."):
            accepted.add(d[4:])
        else:
            accepted.add("www." + d)

    try:
        hrefs = page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href]');
                return Array.from(links).map(a => a.href).filter(Boolean);
            }
        """)
        links = []
        for href in (hrefs or []):
            try:
                parsed = urlparse(href)
                # Remove fragment
                clean = parsed._replace(fragment="").geturl()
                if parsed.netloc in accepted or not parsed.netloc:
                    links.append(clean)
            except Exception:
                continue
        return list(set(links))
    except Exception as e:
        logger.warning(f"Failed to extract links: {e}")
        return []
