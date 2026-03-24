"""
Tests for vendor detection logic.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from worker.detectors.vendor_detector import (
    detect_vendors_from_page_data,
    is_tracking_url,
    get_vendor_key_for_url,
    load_vendor_signatures,
)


class TestVendorSignatureLoading:
    def test_signatures_load(self):
        sigs = load_vendor_signatures()
        assert len(sigs) > 10
        keys = [s.key for s in sigs]
        assert "google_analytics" in keys
        assert "meta_pixel" in keys
        assert "onetrust" in keys

    def test_all_signatures_have_required_fields(self):
        sigs = load_vendor_signatures()
        for sig in sigs:
            assert sig.key
            assert sig.name
            assert sig.category
            assert isinstance(sig.domains, list)
            assert isinstance(sig.script_patterns, list)
            assert isinstance(sig.window_globals, list)
            assert isinstance(sig.cookie_patterns, list)


class TestGoogleAnalyticsDetection:
    def test_detect_via_script_src(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[],
            script_srcs=["https://www.googletagmanager.com/gtag/js?id=G-XXXXXXX"],
            window_globals=[],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "google_analytics" in vendor_keys

    def test_detect_via_domain(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=["https://www.google-analytics.com/g/collect?v=2&tid=G-123"],
            script_srcs=[],
            window_globals=[],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "google_analytics" in vendor_keys

    def test_detect_via_window_global(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[],
            script_srcs=[],
            window_globals=["gtag", "dataLayer"],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "google_analytics" in vendor_keys

    def test_detect_via_cookie(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[],
            script_srcs=[],
            window_globals=[],
            cookie_names=["_ga", "_gid"],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "google_analytics" in vendor_keys


class TestGoogleTagManagerDetection:
    def test_detect_via_domain(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=["https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"],
            script_srcs=[],
            window_globals=[],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "google_tag_manager" in vendor_keys


class TestMetaPixelDetection:
    def test_detect_via_script_src(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[],
            script_srcs=["https://connect.facebook.net/en_US/fbevents.js"],
            window_globals=[],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "meta_pixel" in vendor_keys

    def test_detect_via_cookie(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[],
            script_srcs=[],
            window_globals=[],
            cookie_names=["_fbp"],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "meta_pixel" in vendor_keys

    def test_detect_via_window_global(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[],
            script_srcs=[],
            window_globals=["fbq"],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "meta_pixel" in vendor_keys


class TestOneTrustDetection:
    def test_detect_via_domain(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=["https://cdn.cookielaw.org/scripttemplates/otSDKStub.js"],
            script_srcs=[],
            window_globals=[],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "onetrust" in vendor_keys

    def test_detect_via_cookie(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[],
            script_srcs=[],
            window_globals=[],
            cookie_names=["OptanonConsent"],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "onetrust" in vendor_keys

    def test_detect_via_window_global(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[],
            script_srcs=[],
            window_globals=["OneTrust"],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "onetrust" in vendor_keys


class TestIsTrackingUrl:
    def test_ga_is_tracking(self):
        assert is_tracking_url("https://www.google-analytics.com/g/collect") is True

    def test_gtm_is_tracking(self):
        assert is_tracking_url("https://www.googletagmanager.com/gtm.js") is True

    def test_facebook_is_tracking(self):
        assert is_tracking_url("https://connect.facebook.net/en_US/fbevents.js") is True

    def test_random_url_not_tracking(self):
        assert is_tracking_url("https://example.com/about") is False

    def test_cdn_js_not_tracking(self):
        assert is_tracking_url("https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js") is False


class TestMultipleVendorsDetected:
    def test_multiple_vendors_at_once(self):
        matches = detect_vendors_from_page_data(
            network_request_urls=[
                "https://www.googletagmanager.com/gtm.js?id=GTM-XXX",
                "https://cdn.cookielaw.org/scripttemplates/otSDKStub.js",
                "https://connect.facebook.net/en_US/fbevents.js",
            ],
            script_srcs=[],
            window_globals=[],
            cookie_names=[],
        )
        vendor_keys = [m.vendor_key for m in matches]
        assert "google_tag_manager" in vendor_keys
        assert "onetrust" in vendor_keys
        assert "meta_pixel" in vendor_keys

    def test_detection_returns_unique_vendors(self):
        """Same vendor should only appear once even if multiple signals match."""
        matches = detect_vendors_from_page_data(
            network_request_urls=["https://www.google-analytics.com/g/collect"],
            script_srcs=["https://www.googletagmanager.com/gtag/js?id=G-XXX"],
            window_globals=["gtag"],
            cookie_names=["_ga", "_gid"],
        )
        ga_matches = [m for m in matches if m.vendor_key == "google_analytics"]
        assert len(ga_matches) == 1
