"""
Tests for issue detection rules.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import pytest
from unittest.mock import MagicMock
from datetime import datetime


def make_audit_run(config_id=None):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.base_url = "https://example.com"
    run.config_id = config_id or uuid.uuid4()
    return run


def make_page(audit_run_id=None, url="https://example.com/page", page_group="/page", redirect_chain=None):
    page = MagicMock()
    page.id = uuid.uuid4()
    page.audit_run_id = audit_run_id or uuid.uuid4()
    page.url = url
    page.final_url = url
    page.page_group = page_group
    page.redirect_chain = redirect_chain or []
    return page


def make_network_request(page_visit_id=None, audit_run_id=None, url="https://google-analytics.com/g/collect",
                          failed=False, status_code=200, is_tracking=True, resource_type="xhr"):
    req = MagicMock()
    req.id = uuid.uuid4()
    req.page_visit_id = page_visit_id or uuid.uuid4()
    req.audit_run_id = audit_run_id or uuid.uuid4()
    req.url = url
    req.method = "GET"
    req.failed = failed
    req.status_code = status_code
    req.is_tracking_related = is_tracking
    req.resource_type = resource_type
    req.failure_reason = "net::ERR_CONNECTION_REFUSED" if failed else None
    return req


def make_console_event(page_visit_id=None, audit_run_id=None, level="error", message="ReferenceError: gtag is not defined"):
    evt = MagicMock()
    evt.id = uuid.uuid4()
    evt.page_visit_id = page_visit_id or uuid.uuid4()
    evt.audit_run_id = audit_run_id or uuid.uuid4()
    evt.level = level
    evt.message = message
    evt.source_url = "https://example.com/script.js"
    evt.line_number = 42
    evt.column_number = 10
    return evt


def make_vendor(audit_run_id=None, page_visit_id=None, vendor_key="google_analytics",
                vendor_name="Google Analytics", category="analytics"):
    v = MagicMock()
    v.id = uuid.uuid4()
    v.audit_run_id = audit_run_id or uuid.uuid4()
    v.page_visit_id = page_visit_id
    v.vendor_key = vendor_key
    v.vendor_name = vendor_name
    v.category = category
    return v


def make_config(expected_vendors=None, consent_behavior="no_interaction"):
    cfg = MagicMock()
    cfg.expected_vendors = expected_vendors or []
    cfg.consent_behavior = consent_behavior
    return cfg


class TestBrokenTrackingRequestRule:
    def test_detects_404_tracking_request(self):
        from worker.rules.rule_engine import _rule_broken_tracking_request

        audit_run = make_audit_run()
        pages = [make_page(audit_run_id=audit_run.id)]
        vendors = []

        req = make_network_request(
            audit_run_id=audit_run.id,
            url="https://google-analytics.com/g/collect",
            failed=False,
            status_code=404,
            is_tracking=True,
        )

        issues = _rule_broken_tracking_request(audit_run, pages, [req], vendors)
        assert len(issues) >= 1
        assert issues[0].severity == "high"
        assert "404" in issues[0].title or "broken" in issues[0].title.lower()

    def test_detects_failed_tracking_request(self):
        from worker.rules.rule_engine import _rule_broken_tracking_request

        audit_run = make_audit_run()
        pages = [make_page(audit_run_id=audit_run.id)]

        req = make_network_request(
            audit_run_id=audit_run.id,
            url="https://connect.facebook.net/en_US/fbevents.js",
            failed=True,
            status_code=None,
            is_tracking=True,
        )

        issues = _rule_broken_tracking_request(audit_run, pages, [req], [])
        assert len(issues) >= 1

    def test_no_issue_for_successful_request(self):
        from worker.rules.rule_engine import _rule_broken_tracking_request

        audit_run = make_audit_run()
        pages = [make_page(audit_run_id=audit_run.id)]

        req = make_network_request(
            audit_run_id=audit_run.id,
            url="https://google-analytics.com/g/collect",
            failed=False,
            status_code=200,
            is_tracking=True,
        )

        issues = _rule_broken_tracking_request(audit_run, pages, [req], [])
        assert len(issues) == 0

    def test_no_issue_for_non_tracking_request(self):
        from worker.rules.rule_engine import _rule_broken_tracking_request

        audit_run = make_audit_run()
        pages = [make_page(audit_run_id=audit_run.id)]

        req = make_network_request(
            audit_run_id=audit_run.id,
            url="https://example.com/api/data",
            failed=True,
            status_code=500,
            is_tracking=False,
        )

        issues = _rule_broken_tracking_request(audit_run, pages, [req], [])
        assert len(issues) == 0


class TestMissingExpectedVendorRule:
    def test_detects_missing_vendor(self):
        from worker.rules.rule_engine import _rule_missing_expected_vendor

        audit_run = make_audit_run()
        config = make_config(expected_vendors=["google_analytics", "onetrust"])
        vendors = [make_vendor(vendor_key="onetrust")]  # GA is missing

        issues = _rule_missing_expected_vendor(audit_run, config, vendors)
        assert len(issues) == 1
        assert "google_analytics" in issues[0].affected_vendor_key
        assert issues[0].severity == "high"

    def test_no_issue_when_all_vendors_present(self):
        from worker.rules.rule_engine import _rule_missing_expected_vendor

        audit_run = make_audit_run()
        config = make_config(expected_vendors=["google_analytics", "onetrust"])
        vendors = [
            make_vendor(vendor_key="google_analytics"),
            make_vendor(vendor_key="onetrust"),
        ]

        issues = _rule_missing_expected_vendor(audit_run, config, vendors)
        assert len(issues) == 0

    def test_no_issue_with_empty_expected_vendors(self):
        from worker.rules.rule_engine import _rule_missing_expected_vendor

        audit_run = make_audit_run()
        config = make_config(expected_vendors=[])
        vendors = []

        issues = _rule_missing_expected_vendor(audit_run, config, vendors)
        assert len(issues) == 0

    def test_multiple_missing_vendors(self):
        from worker.rules.rule_engine import _rule_missing_expected_vendor

        audit_run = make_audit_run()
        config = make_config(expected_vendors=["google_analytics", "meta_pixel", "onetrust"])
        vendors = []  # None detected

        issues = _rule_missing_expected_vendor(audit_run, config, vendors)
        assert len(issues) == 3


class TestConsentIssueRule:
    def test_flags_tracking_without_consent(self):
        from worker.rules.rule_engine import _rule_consent_issue_no_interaction

        audit_run = make_audit_run()
        config = make_config(consent_behavior="no_interaction")

        page_id = uuid.uuid4()
        page = make_page(url="https://example.com/", page_group="/")
        page.id = page_id

        page_vendors = [
            make_vendor(page_visit_id=page_id, vendor_key="onetrust", category="consent"),
            make_vendor(page_visit_id=page_id, vendor_key="google_analytics", category="analytics"),
        ]

        issues = _rule_consent_issue_no_interaction(audit_run, config, [page], page_vendors)
        assert len(issues) >= 1
        issue = issues[0]
        assert issue.category == "consent"
        assert issue.severity == "high"

    def test_no_issue_when_no_consent_manager(self):
        from worker.rules.rule_engine import _rule_consent_issue_no_interaction

        audit_run = make_audit_run()
        config = make_config(consent_behavior="no_interaction")

        page_id = uuid.uuid4()
        page = make_page()
        page.id = page_id

        # Only tracking vendor, no CMP
        page_vendors = [
            make_vendor(page_visit_id=page_id, vendor_key="google_analytics", category="analytics"),
        ]

        issues = _rule_consent_issue_no_interaction(audit_run, config, [page], page_vendors)
        assert len(issues) == 0

    def test_no_issue_when_consent_accepted(self):
        from worker.rules.rule_engine import _rule_consent_issue_no_interaction

        audit_run = make_audit_run()
        config = make_config(consent_behavior="accept_consent")

        page_id = uuid.uuid4()
        page = make_page()
        page.id = page_id

        page_vendors = [
            make_vendor(page_visit_id=page_id, vendor_key="onetrust", category="consent"),
            make_vendor(page_visit_id=page_id, vendor_key="google_analytics", category="analytics"),
        ]

        issues = _rule_consent_issue_no_interaction(audit_run, config, [page], page_vendors)
        assert len(issues) == 0


class TestFailedScriptLoadRule:
    def test_detects_failed_js_load(self):
        from worker.rules.rule_engine import _rule_failed_script_load

        audit_run = make_audit_run()
        pages = [make_page()]

        req = make_network_request(
            url="https://cdn.segment.com/analytics.js",
            failed=True,
            status_code=None,
            is_tracking=True,
            resource_type="script",
        )

        issues = _rule_failed_script_load(audit_run, pages, [req], [])
        assert len(issues) >= 1
        assert issues[0].severity == "critical"

    def test_no_issue_for_loaded_script(self):
        from worker.rules.rule_engine import _rule_failed_script_load

        audit_run = make_audit_run()
        pages = [make_page()]

        req = make_network_request(
            url="https://cdn.segment.com/analytics.js",
            failed=False,
            status_code=200,
            is_tracking=True,
            resource_type="script",
        )

        issues = _rule_failed_script_load(audit_run, pages, [req], [])
        assert len(issues) == 0


class TestConsoleErrorsRule:
    def test_detects_multiple_console_errors(self):
        from worker.rules.rule_engine import _rule_console_js_errors

        audit_run = make_audit_run()
        page_id = uuid.uuid4()
        pages = [make_page()]

        events = [
            make_console_event(page_visit_id=page_id, level="error", message=f"Error {i}")
            for i in range(5)
        ]

        issues = _rule_console_js_errors(audit_run, pages, events)
        assert len(issues) >= 1
        assert issues[0].severity in ("high", "medium")

    def test_no_issue_for_few_errors(self):
        from worker.rules.rule_engine import _rule_console_js_errors

        audit_run = make_audit_run()
        page_id = uuid.uuid4()
        pages = [make_page()]

        events = [
            make_console_event(page_visit_id=page_id, level="error", message="One error")
        ]

        issues = _rule_console_js_errors(audit_run, pages, events)
        assert len(issues) == 0

    def test_no_issue_for_warnings(self):
        from worker.rules.rule_engine import _rule_console_js_errors

        audit_run = make_audit_run()
        page_id = uuid.uuid4()
        pages = [make_page()]

        events = [
            make_console_event(page_visit_id=page_id, level="warning", message=f"Warning {i}")
            for i in range(10)
        ]

        issues = _rule_console_js_errors(audit_run, pages, events)
        assert len(issues) == 0
