"""
Vendor detector: loads signatures from vendors.yaml and detects vendors
across pages by matching network requests, script URLs, window globals, and cookies.
"""
import os
import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import yaml

logger = logging.getLogger("odit.worker.vendor_detector")

VENDORS_YAML_PATH = os.path.join(os.path.dirname(__file__), "vendors.yaml")


@dataclass
class VendorSignature:
    key: str
    name: str
    category: str
    domains: List[str] = field(default_factory=list)
    script_patterns: List[str] = field(default_factory=list)
    window_globals: List[str] = field(default_factory=list)
    cookie_patterns: List[str] = field(default_factory=list)


@dataclass
class VendorMatch:
    vendor_key: str
    vendor_name: str
    category: str
    detection_method: str  # domain / script_src / window_global / cookie
    evidence: Dict[str, Any]


def load_vendor_signatures() -> List[VendorSignature]:
    with open(VENDORS_YAML_PATH, "r") as f:
        data = yaml.safe_load(f)

    signatures = []
    for v in data.get("vendors", []):
        sigs = v.get("signatures", {})
        signatures.append(VendorSignature(
            key=v["key"],
            name=v["name"],
            category=v["category"],
            domains=sigs.get("domains", []),
            script_patterns=sigs.get("script_patterns", []),
            window_globals=sigs.get("window_globals", []),
            cookie_patterns=sigs.get("cookie_patterns", []),
        ))
    return signatures


_signatures: Optional[List[VendorSignature]] = None


def get_signatures() -> List[VendorSignature]:
    global _signatures
    if _signatures is None:
        _signatures = load_vendor_signatures()
    return _signatures


def detect_vendors_from_page_data(
    network_request_urls: List[str],
    script_srcs: List[str],
    window_globals: List[str],
    cookie_names: List[str],
) -> List[VendorMatch]:
    """
    Given arrays of evidence from a page, return list of detected vendors.
    """
    signatures = get_signatures()
    matches: Dict[str, VendorMatch] = {}

    for sig in signatures:
        # Check domain matches against network requests
        for req_url in network_request_urls:
            for domain in sig.domains:
                if domain in req_url:
                    if sig.key not in matches:
                        matches[sig.key] = VendorMatch(
                            vendor_key=sig.key,
                            vendor_name=sig.name,
                            category=sig.category,
                            detection_method="domain",
                            evidence={"matched_domain": domain, "matched_url": req_url[:200]},
                        )
                    break
            if sig.key in matches:
                break

        # Check script src patterns
        if sig.key not in matches:
            for script_url in script_srcs:
                for pattern in sig.script_patterns:
                    if pattern in script_url:
                        matches[sig.key] = VendorMatch(
                            vendor_key=sig.key,
                            vendor_name=sig.name,
                            category=sig.category,
                            detection_method="script_src",
                            evidence={"matched_pattern": pattern, "script_url": script_url[:200]},
                        )
                        break
                if sig.key in matches:
                    break

        # Check window globals
        if sig.key not in matches:
            for global_name in sig.window_globals:
                if global_name in window_globals:
                    matches[sig.key] = VendorMatch(
                        vendor_key=sig.key,
                        vendor_name=sig.name,
                        category=sig.category,
                        detection_method="window_global",
                        evidence={"matched_global": global_name},
                    )
                    break

        # Check cookie patterns
        if sig.key not in matches:
            for cookie_pattern in sig.cookie_patterns:
                for cookie_name in cookie_names:
                    if cookie_name.startswith(cookie_pattern) or cookie_pattern in cookie_name:
                        matches[sig.key] = VendorMatch(
                            vendor_key=sig.key,
                            vendor_name=sig.name,
                            category=sig.category,
                            detection_method="cookie",
                            evidence={"matched_cookie_pattern": cookie_pattern, "cookie_name": cookie_name},
                        )
                        break
                if sig.key in matches:
                    break

    return list(matches.values())


def is_tracking_url(url: str) -> bool:
    """Quick check if a URL is likely tracking-related."""
    signatures = get_signatures()
    for sig in signatures:
        for domain in sig.domains:
            if domain in url:
                return True
        for pattern in sig.script_patterns:
            if pattern in url:
                return True
    return False


def get_vendor_key_for_url(url: str) -> Optional[str]:
    """Return the vendor key that matches a URL, if any."""
    signatures = get_signatures()
    for sig in signatures:
        for domain in sig.domains:
            if domain in url:
                return sig.key
        for pattern in sig.script_patterns:
            if pattern in url:
                return sig.key
    return None
