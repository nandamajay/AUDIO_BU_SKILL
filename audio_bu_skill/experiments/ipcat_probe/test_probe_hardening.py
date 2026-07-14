#!/usr/bin/env python3
"""
Offline tests for the Phase-1A probe hardening.

No network, no provisioning, no external deps: these exercise the pure logic
(_resolve_chip_in named-field matching, _classify_error redaction, timeout
helper, exit-code contract via monkeypatched probe paths).

Run:  python test_probe_hardening.py         # or: python -O test_probe_hardening.py
"""

import concurrent.futures
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402


class TestNamedFieldResolution(unittest.TestCase):
    def test_exact_named_field_resolves(self):
        resp = {"chips": [{"chip_id": "sa8775p", "name": "Nord-IQ10"},
                          {"chip_id": "xyz", "name": "Other"}]}
        r = probe._resolve_chip_in(resp, "sa8775p")
        self.assertEqual(r["status"], "RESOLVED")
        self.assertTrue(r["resolved"])
        self.assertEqual(r["matched_field"], "chip_id")

    def test_substring_no_longer_false_positives(self):
        # "775" is a substring of the id but NOT a whole identifier value.
        resp = {"chips": [{"chip_id": "sa8775p", "name": "Nord"}]}
        r = probe._resolve_chip_in(resp, "775")
        self.assertEqual(r["status"], "ABSENT")
        self.assertFalse(r["resolved"])

    def test_no_match_in_nonidentifier_field(self):
        # value appears only in a non-identifier field (description) -> ABSENT
        resp = {"chips": [{"chip_id": "abc", "description": "contains nord"}]}
        r = probe._resolve_chip_in(resp, "nord")
        self.assertEqual(r["status"], "ABSENT")

    def test_alias_list_matches(self):
        resp = {"chips": [{"chip_id": "abc", "aliases": ["nord", "iq10"]}]}
        r = probe._resolve_chip_in(resp, "IQ10")
        self.assertEqual(r["status"], "RESOLVED")
        self.assertEqual(r["matched_field"], "aliases")

    def test_ambiguous_detected(self):
        resp = {"chips": [{"chip_id": "dup", "name": "A"},
                          {"name": "dup"}]}
        r = probe._resolve_chip_in(resp, "dup")
        self.assertEqual(r["status"], "AMBIGUOUS")
        self.assertFalse(r["resolved"])
        self.assertEqual(len(r["candidates"]), 2)

    def test_same_row_two_fields_not_ambiguous(self):
        resp = {"chips": [{"chip_id": "nord", "name": "nord"}]}
        r = probe._resolve_chip_in(resp, "nord")
        self.assertEqual(r["status"], "RESOLVED")

    def test_prose_is_unstructured(self):
        r = probe._resolve_chip_in("just prose", "nord")
        self.assertEqual(r["status"], "UNSTRUCTURED")

    def test_list_root(self):
        resp = [{"chip_id": "nord"}]
        r = probe._resolve_chip_in(resp, "nord")
        self.assertEqual(r["status"], "RESOLVED")


class TestErrorClassification(unittest.TestCase):
    def test_tls_category(self):
        class SSLCertVerificationError(Exception):
            pass
        note = probe._classify_error(SSLCertVerificationError("x"))
        self.assertTrue(note.startswith("tls_verification_failed"))

    def test_dns_category(self):
        class gaierror(Exception):
            pass
        self.assertTrue(probe._classify_error(gaierror()).startswith("dns_failure"))

    def test_connect_category(self):
        class ConnectError(Exception):
            pass
        self.assertTrue(probe._classify_error(ConnectError()).startswith("connection_failed"))

    def test_no_message_leak(self):
        # A token-looking secret in the message must NOT appear in the label.
        class ConnectError(Exception):
            pass
        note = probe._classify_error(ConnectError("Bearer SECRET_TOKEN_123"))
        self.assertNotIn("SECRET_TOKEN_123", note)

    def test_chain_walk(self):
        inner = ValueError("inner")
        try:
            try:
                raise inner
            except ValueError as e:
                raise RuntimeError("outer") from e
        except RuntimeError as exc:
            note = probe._classify_error(exc)
        self.assertIn("RuntimeError", note)
        self.assertIn("ValueError", note)


class TestTimeout(unittest.TestCase):
    def test_timeout_raises(self):
        orig = probe.PROBE_TIMEOUT_SECONDS
        probe.PROBE_TIMEOUT_SECONDS = 0.2
        try:
            with self.assertRaises(concurrent.futures.TimeoutError):
                probe._call_with_timeout(lambda: time.sleep(2))
        finally:
            probe.PROBE_TIMEOUT_SECONDS = orig

    def test_fast_call_returns(self):
        self.assertEqual(probe._call_with_timeout(lambda: 42), 42)


class TestExitCodeContract(unittest.TestCase):
    """Exercise probe_path_b via a fake ipcat_client injected into sys.modules."""

    def _run_with_fake(self, fake_get_chips, chip="nord", token="t"):
        import types
        mod = types.ModuleType("ipcat_client")
        mod.get_chips = fake_get_chips
        sys.modules["ipcat_client"] = mod
        os.environ["IPCAT_TOKEN"] = token
        try:
            return probe.probe_path_b(chip)
        finally:
            sys.modules.pop("ipcat_client", None)
            os.environ.pop("IPCAT_TOKEN", None)

    def test_success(self):
        r = self._run_with_fake(lambda: {"chips": [{"chip_id": "nord"}]})
        self.assertTrue(r["connected"] and r["structured"] and r["nord_resolved"])

    def test_partial_unresolved(self):
        r = self._run_with_fake(lambda: {"chips": [{"chip_id": "other"}]})
        self.assertTrue(r["connected"])
        self.assertFalse(r["nord_resolved"])

    def test_partial_prose(self):
        r = self._run_with_fake(lambda: "prose not json")
        self.assertTrue(r["connected"])
        self.assertFalse(r["structured"])

    def test_failure_exception_caught(self):
        def boom():
            raise RuntimeError("Bearer LEAKME")
        r = self._run_with_fake(boom)
        self.assertFalse(r["connected"])
        self.assertNotIn("LEAKME", r["note"])

    def test_no_credential_is_failure(self):
        # No token env set -> not connected
        sys.modules.pop("ipcat_client", None)
        r = probe.probe_path_b("nord")
        self.assertFalse(r["connected"])


class TestReadOnlyGuardStillEnforced(unittest.TestCase):
    def test_guard_rejects(self):
        with self.assertRaises(PermissionError):
            probe._require_readonly("write_tool", probe.READONLY_MCP_TOOLS)

    def test_authjson_guard(self):
        with self.assertRaises(PermissionError):
            probe._assert_not_forbidden("/x/auth.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
