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


def extract_cookies(context) -> List[Dict[str, str]]:
    """Extract cookies from browser context."""
    try:
        cookies = context.cookies()
        return [{"name": c["name"], "domain": c.get("domain", ""), "path": c.get("path", "/")} for c in cookies]
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
        "_satellite", "s_gi", "AppMeasurement",
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


def take_screenshot(page, output_path: str) -> Optional[str]:
    """Take a full-page screenshot and save to output_path."""
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        page.screenshot(path=output_path, full_page=True, timeout=15000)
        return output_path
    except Exception as e:
        logger.warning(f"Screenshot failed: {e}")
        return None


def extract_links(page, base_domain: str) -> List[str]:
    """Extract all internal links from the page."""
    from urllib.parse import urlparse, urljoin
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
                if parsed.netloc == base_domain or not parsed.netloc:
                    links.append(clean)
            except Exception:
                continue
        return list(set(links))
    except Exception as e:
        logger.warning(f"Failed to extract links: {e}")
        return []
