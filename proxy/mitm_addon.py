"""
mitmproxy addon script for Odit.
Intercepts all HTTP(S) flows and writes structured JSON records to disk.
"""
import os
import json
import time
import re
from mitmproxy import http

# Known tracking domains for quick tagging
TRACKING_DOMAINS = [
    "google-analytics.com",
    "analytics.google.com",
    "googletagmanager.com",
    "assets.adobedtm.com",
    "omtrdc.net",
    "sc.omtrdc.net",
    "tags.tiqcdn.com",
    "cdn.segment.com",
    "api.segment.io",
    "cdn.rudderlabs.com",
    "cdn.mxpnl.com",
    "api.mixpanel.com",
    "cdn.amplitude.com",
    "api.amplitude.com",
    "cdn.heapanalytics.com",
    "heapanalytics.com",
    "connect.facebook.net",
    "snap.licdn.com",
    "analytics.tiktok.com",
    "cdn.optimizely.com",
    "logx.optimizely.com",
    "dev.visualwebsiteoptimizer.com",
    "tt.omtrdc.net",
    "app.launchdarkly.com",
    "clientsdk.launchdarkly.com",
    "cdn.dynamicyield.com",
    "cdn.cookielaw.org",
    "consent.cookiebot.com",
    "consent.trustarc.com",
]

DATA_DIR = os.environ.get("DATA_DIR", "/data")
FLOWS_DIR = os.path.join(DATA_DIR, "proxy_flows")


def is_tracking_domain(url: str) -> bool:
    for domain in TRACKING_DOMAINS:
        if domain in url:
            return True
    return False


def extract_audit_id_from_headers(headers: dict) -> str:
    """Try to extract audit ID from custom headers."""
    return headers.get("x-odit-audit-id", "unknown")


class OditAddon:
    def __init__(self):
        os.makedirs(FLOWS_DIR, exist_ok=True)

    def response(self, flow: http.HTTPFlow) -> None:
        try:
            url = flow.request.pretty_url
            tracking = is_tracking_domain(url)

            # Get timing if available
            timing_ms = None
            if flow.response and hasattr(flow, "server_conn") and flow.server_conn:
                try:
                    timing_ms = (flow.response.timestamp_end - flow.request.timestamp_start) * 1000
                except Exception:
                    pass

            record = {
                "url": url,
                "method": flow.request.method,
                "status_code": flow.response.status_code if flow.response else None,
                "content_type": flow.response.headers.get("content-type", "") if flow.response else "",
                "request_headers": dict(flow.request.headers),
                "response_headers": dict(flow.response.headers) if flow.response else {},
                "timing_ms": timing_ms,
                "is_tracking_related": tracking,
                "timestamp": time.time(),
            }

            # Determine which directory to write to
            audit_id = extract_audit_id_from_headers(dict(flow.request.headers))
            if audit_id == "unknown":
                audit_id = "global"

            target_dir = os.path.join(FLOWS_DIR, audit_id)
            os.makedirs(target_dir, exist_ok=True)

            # Append to a JSONL file (one record per line)
            flows_file = os.path.join(target_dir, "flows.jsonl")
            with open(flows_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

        except Exception as e:
            pass  # Never crash the proxy

    def request_failed(self, flow: http.HTTPFlow) -> None:
        try:
            url = flow.request.pretty_url
            record = {
                "url": url,
                "method": flow.request.method,
                "status_code": None,
                "failed": True,
                "error": str(flow.error) if flow.error else "unknown",
                "is_tracking_related": is_tracking_domain(url),
                "timestamp": time.time(),
            }

            audit_id = extract_audit_id_from_headers(dict(flow.request.headers))
            if audit_id == "unknown":
                audit_id = "global"

            target_dir = os.path.join(FLOWS_DIR, audit_id)
            os.makedirs(target_dir, exist_ok=True)

            flows_file = os.path.join(target_dir, "flows.jsonl")
            with open(flows_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass


addons = [OditAddon()]
