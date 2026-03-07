"""Tests for the verifier registry (core/registry.py)."""

from __future__ import annotations

import pytest

from vrdev.core.base import BaseVerifier
from vrdev.core.registry import get_verifier, list_verifiers


class TestListVerifiers:
    def test_returns_all_nineteen_ids(self):
        ids = list_verifiers()
        assert len(ids) == 19

    def test_ids_are_sorted(self):
        ids = list_verifiers()
        assert ids == sorted(ids)

    def test_contains_all_expected_ids(self):
        ids = set(list_verifiers())
        expected = {
            "vr/aiv.calendar.event_created",
            "vr/aiv.email.sent_folder_confirmed",
            "vr/aiv.shell.state_probe",
            "vr/code.python.lint_ruff",
            "vr/code.python.tests_pass",
            "vr/filesystem.file_created",
            "vr/git.commit_present",
            "vr/rubric.code.logic_correct",
            "vr/rubric.email.tone_professional",
            "vr/tau2.airline.rebooking_correct",
            "vr/tau2.policy.constraint_not_violated",
            "vr/tau2.retail.order_cancelled",
            "vr/tau2.retail.refund_processed",
            "vr/tau2.telecom.plan_changed",
            "vr/web.browser.element_visible",
            "vr/web.browser.screenshot_match",
            "vr/web.ecommerce.order_placed",
            "vr/rubric.summary.faithful",
            "vr/tau2.retail.inventory_updated",
        }
        assert ids == expected


class TestGetVerifier:
    def test_filesystem_verifier(self):
        v = get_verifier("vr/filesystem.file_created")
        assert isinstance(v, BaseVerifier)
        assert v.name == "filesystem.file_created"

    def test_order_cancelled_verifier(self):
        v = get_verifier("vr/tau2.retail.order_cancelled")
        assert isinstance(v, BaseVerifier)

    def test_policy_verifier(self):
        v = get_verifier("vr/tau2.policy.constraint_not_violated")
        assert isinstance(v, BaseVerifier)

    def test_rebooking_verifier(self):
        v = get_verifier("vr/tau2.airline.rebooking_correct")
        assert isinstance(v, BaseVerifier)

    def test_email_verifier(self):
        v = get_verifier("vr/aiv.email.sent_folder_confirmed")
        assert isinstance(v, BaseVerifier)

    def test_rubric_verifier(self):
        v = get_verifier("vr/rubric.email.tone_professional")
        assert isinstance(v, BaseVerifier)

    def test_passes_kwargs_to_constructor(self):
        """Email verifier accepts imap_runner kwarg."""
        v = get_verifier("vr/aiv.email.sent_folder_confirmed", imap_runner="fake")
        assert v._imap_runner == "fake"

    def test_unknown_id_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown verifier"):
            get_verifier("vr/nonexistent.verifier")

    def test_error_message_includes_available(self):
        with pytest.raises(KeyError, match="Available:"):
            get_verifier("vr/bad")
