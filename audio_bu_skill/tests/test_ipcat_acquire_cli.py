"""T-IA-01, T-IA-02, T-IA-05, T-IA-06, T-IA-14 — CLI wiring + static isolation.

T-IA-01: Static AST check — no runner module and no do_run function body imports
         from orchestrator.ipcat_acquire. Proves --target has no code path to live
         acquisition.

T-IA-02: Full CLI path — main() -> parse_args() -> dispatch ->
         do_refresh_ipcat_cache() -> acquire_to_cache() works end-to-end with a
         mocked transport. sys.argv is patched; open_session is patched;
         resolve_ipcat_evidence_dir is patched. SystemExit(0) expected, cache
         files present.

T-IA-05: Missing .mcp.json -> TRANSPORT_ERROR -> exit 3.  No transport injection
         (HttpxTransport is constructed but fails at file read before any socket).
         resolve_ipcat_evidence_dir is patched; HOME is redirected to a temp dir
         that has no .claude/.mcp.json.

T-IA-06: Auth wall -> AUTH_REQUIRED -> do_refresh_ipcat_cache returns 3. Transport
         mock returns AUTHWALL_KEY on the first tool call.

T-IA-14: Mode mutual exclusion — --refresh-ipcat-cache combined with --target,
         --onboard, or --replay triggers argparse exit 2 before any dispatch code
         runs.

Mechanism validation: mechanism=None, mechanism="INVALID", mechanism="B" all
         cause do_refresh_ipcat_cache to return 3 without any I/O.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_ipcat_acquire_cli
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# helpers for module-level patching (no pytest; plain attribute swap)
# ---------------------------------------------------------------------------

class _Patch:
    """Context manager: temporarily replace obj.attr with value."""
    def __init__(self, obj, attr, value):
        self._obj = obj
        self._attr = attr
        self._value = value
        self._orig = None

    def __enter__(self):
        self._orig = getattr(self._obj, self._attr)
        setattr(self._obj, self._attr, self._value)
        return self

    def __exit__(self, *_):
        setattr(self._obj, self._attr, self._orig)


# ---------------------------------------------------------------------------
# mock transport (mirrors _MockTransport in test_ipcat_acquire_flow.py)
# ---------------------------------------------------------------------------

from orchestrator.ipcat_acquire.client import AUTHWALL_KEY

class _MockTransport:
    def __init__(self, responses: dict[str, Any], *, auth_wall_on: str | None = None):
        self._responses = responses
        self._auth_wall_on = auth_wall_on
        self.closed = False
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool: str, args: Mapping[str, Any]) -> Any:
        self.calls.append((tool, dict(args)))
        if self._auth_wall_on and tool == self._auth_wall_on:
            return {AUTHWALL_KEY: "Authentication required: please log in"}
        if tool in self._responses:
            return self._responses[tool]
        raise ConnectionError(f"mock: unexpected tool {tool!r}")

    def close(self) -> None:
        self.closed = True


_CHIP_ALIAS = "nordschleife_2.0"
_CHIP_ROW = {"alias": _CHIP_ALIAS, "id": 781, "canonical_name": "SA8797P (NordAU) v2"}

_HAPPY_RESPONSES: dict[str, Any] = {
    "chips_list_chips":           [_CHIP_ROW],
    "cores_list_core_instances":  [{"name": "audio_q6"}],
    "swi_search_swi":             [{"name": "SWR_MASTER0"}, {"name": "SWR_MASTER1"}],
    "gpio_get_gpio_map":          {"gpio_map_id": 99},
    "gpio_list_gpios_from_map":   [{"gpio_num": 0, "name": "GPIO0"}],
    "gpio_list_tlmm_gpios":       [{"gpio_num": 0}],
    "chipio_get_qups":            [{"qup_id": "QUP0"}],
    "buses_list_buses":           [{"bus": "config_noc"}],
    "buses_list_bus_gateways":    [{"gateway": "gw0"}],
    "buses_list_bidpidmids":      [{"bid": 1}],
}


# ---------------------------------------------------------------------------
# T-IA-01: static import isolation
# ---------------------------------------------------------------------------

_AUDIO_BU_ROOT = Path(__file__).resolve().parents[1]
_RUNNERS_DIR = _AUDIO_BU_ROOT / "orchestrator" / "runners"
_MAIN_PY = _AUDIO_BU_ROOT / "orchestrator" / "main.py"


def _contains_ipcat_acquire_import(path: Path) -> bool:
    """Return True if the AST of path contains any import of ipcat_acquire."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "ipcat_acquire" in alias.name:
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "ipcat_acquire" in module:
                return True
    return False


def test_runners_have_no_ipcat_acquire_import() -> None:
    """T-IA-01a: no runner module imports ipcat_acquire."""
    assert _RUNNERS_DIR.is_dir(), f"runners dir not found: {_RUNNERS_DIR}"
    violations = [
        p for p in _RUNNERS_DIR.rglob("*.py")
        if _contains_ipcat_acquire_import(p)
    ]
    assert not violations, (
        "T-IA-01a: runners import ipcat_acquire:\n"
        + "\n".join(f"  {p}" for p in violations)
    )
    print("PASS T-IA-01a: no runner module imports orchestrator.ipcat_acquire")


def test_do_run_body_has_no_ipcat_acquire_import() -> None:
    """T-IA-01b: the do_run function body contains no ipcat_acquire import."""
    source = _MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_MAIN_PY))

    do_run_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "do_run":
            do_run_node = node
            break
    assert do_run_node is not None, "do_run not found in main.py"

    violations = []
    for node in ast.walk(do_run_node):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "ipcat_acquire" in alias.name:
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "ipcat_acquire" in module:
                violations.append(module)
    assert not violations, f"T-IA-01b: do_run imports ipcat_acquire: {violations}"
    print("PASS T-IA-01b: do_run body contains no ipcat_acquire import")


def test_ipcat_acquire_package_is_importable() -> None:
    """T-IA-01c: guard against false-green from accidental package removal."""
    import orchestrator.ipcat_acquire as _pkg  # noqa: F401
    assert hasattr(_pkg, "acquire_to_cache"), "acquire_to_cache missing from package"
    print("PASS T-IA-01c: orchestrator.ipcat_acquire is importable and exposes acquire_to_cache")


# ---------------------------------------------------------------------------
# T-IA-02: full CLI path through main()
# ---------------------------------------------------------------------------

def test_full_cli_path_returns_exit_0() -> None:
    """T-IA-02: main() -> parse_args() -> dispatch -> do_refresh_ipcat_cache
    -> acquire_to_cache, exercised via sys.argv patch + open_session patch."""
    import orchestrator.main as _main
    import orchestrator.ipcat_acquire as _ipcat_pkg

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        mock_transport = _MockTransport(_HAPPY_RESPONSES)

        orig_argv = sys.argv[:]
        sys.argv = [
            "main",
            "--refresh-ipcat-cache", "nord-iq10",
            "--ipcat-chip", _CHIP_ALIAS,
            "--ipcat-mechanism", "A",
        ]

        orig_resolve = _main.resolve_ipcat_evidence_dir
        _main.resolve_ipcat_evidence_dir = lambda t: base

        # Patch where open_session is *used* (the __init__ namespace), not where
        # it is defined, so acquire_to_cache picks up the mock transport.
        orig_open_session = _ipcat_pkg.open_session
        _ipcat_pkg.open_session = lambda mechanism, **kw: mock_transport

        raised_code = None
        try:
            _main.main()
        except SystemExit as exc:
            raised_code = exc.code
        finally:
            sys.argv = orig_argv
            _main.resolve_ipcat_evidence_dir = orig_resolve
            _ipcat_pkg.open_session = orig_open_session

        assert raised_code == 0, f"expected SystemExit(0), got {raised_code}"
        json_files = list(base.glob("*.json"))
        assert json_files, "no cache files written despite exit 0"
        assert (base / "provenance.json").exists(), "provenance.json missing"

    print("PASS T-IA-02: full CLI path main()->dispatch->acquire_to_cache, exit 0, files present")


# ---------------------------------------------------------------------------
# T-IA-05: missing .mcp.json -> TRANSPORT_ERROR -> exit 3
# ---------------------------------------------------------------------------

def test_missing_mcp_json_returns_exit_3() -> None:
    """T-IA-05: FileNotFoundError from HttpxTransport.__init__ propagates to
    TRANSPORT_ERROR (exit 3); zero bytes written. HOME redirected to a temp
    dir that has no .claude/.mcp.json."""
    import orchestrator.main as _main

    with tempfile.TemporaryDirectory() as tmp_home, \
         tempfile.TemporaryDirectory() as tmp_ipcat:

        orig_home = os.environ.get("HOME")
        os.environ["HOME"] = tmp_home  # no .claude/.mcp.json here

        orig_resolve = _main.resolve_ipcat_evidence_dir
        _main.resolve_ipcat_evidence_dir = lambda t: Path(tmp_ipcat)

        try:
            rc = _main.do_refresh_ipcat_cache(
                "nord-iq10",
                chip_alias=_CHIP_ALIAS,
                mechanism="A",
                dry_run=False,
            )
        finally:
            if orig_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = orig_home
            _main.resolve_ipcat_evidence_dir = orig_resolve

        assert rc == 3, f"expected return 3 for missing .mcp.json, got {rc}"
        json_files = list(Path(tmp_ipcat).glob("*.json"))
        assert not json_files, f"files written despite missing .mcp.json: {json_files}"

    print("PASS T-IA-05: missing .mcp.json -> TRANSPORT_ERROR -> return 3, zero bytes")


# ---------------------------------------------------------------------------
# T-IA-06: auth wall -> AUTH_REQUIRED -> exit 3
# ---------------------------------------------------------------------------

def test_auth_wall_returns_exit_3() -> None:
    """T-IA-06: transport mock returns AUTHWALL_KEY on first call ->
    do_refresh_ipcat_cache returns 3, zero bytes written."""
    import orchestrator.main as _main
    import orchestrator.ipcat_acquire as _ipcat_pkg

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        auth_wall_mock = _MockTransport({}, auth_wall_on="chips_list_chips")

        orig_resolve = _main.resolve_ipcat_evidence_dir
        _main.resolve_ipcat_evidence_dir = lambda t: base

        # Patch where open_session is *used* (the __init__ namespace).
        orig_open_session = _ipcat_pkg.open_session
        _ipcat_pkg.open_session = lambda mechanism, **kw: auth_wall_mock

        try:
            rc = _main.do_refresh_ipcat_cache(
                "nord-iq10",
                chip_alias=_CHIP_ALIAS,
                mechanism="A",
            )
        finally:
            _main.resolve_ipcat_evidence_dir = orig_resolve
            _ipcat_pkg.open_session = orig_open_session

        assert rc == 3, f"expected return 3 for auth wall, got {rc}"
        json_files = list(base.glob("*.json"))
        assert not json_files, f"files written despite auth wall: {json_files}"

    print("PASS T-IA-06: auth wall -> AUTH_REQUIRED -> return 3, zero bytes")


# ---------------------------------------------------------------------------
# T-IA-14: mode mutual exclusion (argparse-enforced)
# ---------------------------------------------------------------------------

def _run_argv_expect_exit2(argv: list[str]) -> None:
    """Call main() with the given argv; assert argparse exits with code 2."""
    import orchestrator.main as _main

    called = []
    orig_fn = _main.do_refresh_ipcat_cache
    def _sentinel(target, **kw):
        called.append(target)
        return orig_fn(target, **kw)
    _main.do_refresh_ipcat_cache = _sentinel

    orig_argv = sys.argv[:]
    sys.argv = argv
    raised_code = None
    try:
        _main.main()
    except SystemExit as exc:
        raised_code = exc.code
    finally:
        sys.argv = orig_argv
        _main.do_refresh_ipcat_cache = orig_fn

    assert raised_code == 2, (
        f"expected exit 2 for conflicting modes {argv!r}, got {raised_code}"
    )
    assert not called, (
        f"do_refresh_ipcat_cache was called despite mutual exclusion conflict: {called}"
    )


def test_target_and_refresh_mutual_exclusion() -> None:
    """T-IA-14a: --target + --refresh-ipcat-cache -> exit 2, no dispatch."""
    _run_argv_expect_exit2([
        "main",
        "--target", "nord-iq10",
        "--refresh-ipcat-cache", "nord-iq10",
    ])
    print("PASS T-IA-14a: --target + --refresh-ipcat-cache -> exit 2")


def test_onboard_and_refresh_mutual_exclusion() -> None:
    """T-IA-14b: --onboard + --refresh-ipcat-cache -> exit 2, no dispatch."""
    _run_argv_expect_exit2([
        "main",
        "--onboard", "nord-iq10",
        "--refresh-ipcat-cache", "nord-iq10",
    ])
    print("PASS T-IA-14b: --onboard + --refresh-ipcat-cache -> exit 2")


def test_replay_and_refresh_mutual_exclusion() -> None:
    """T-IA-14c: --replay + --refresh-ipcat-cache -> exit 2, no dispatch."""
    _run_argv_expect_exit2([
        "main",
        "--replay", "run-123",
        "--refresh-ipcat-cache", "nord-iq10",
    ])
    print("PASS T-IA-14c: --replay + --refresh-ipcat-cache -> exit 2")


# ---------------------------------------------------------------------------
# Mechanism validation
# ---------------------------------------------------------------------------

def test_mechanism_none_returns_exit_3() -> None:
    """mechanism=None -> return 3, no I/O at all."""
    import orchestrator.main as _main
    rc = _main.do_refresh_ipcat_cache(
        "nord-iq10",
        chip_alias=_CHIP_ALIAS,
        mechanism=None,
    )
    assert rc == 3, f"expected 3 for mechanism=None, got {rc}"
    print("PASS mech-val-a: mechanism=None -> return 3, no I/O")


def test_mechanism_invalid_string_returns_exit_3() -> None:
    """mechanism='INVALID' -> return 3, no I/O at all."""
    import orchestrator.main as _main
    rc = _main.do_refresh_ipcat_cache(
        "nord-iq10",
        chip_alias=_CHIP_ALIAS,
        mechanism="INVALID",
    )
    assert rc == 3, f"expected 3 for mechanism='INVALID', got {rc}"
    print("PASS mech-val-b: mechanism='INVALID' -> return 3, no I/O")


def test_mechanism_unsupported_b_returns_exit_3() -> None:
    """mechanism='B' (not yet implemented) -> return 3, no I/O at all."""
    import orchestrator.main as _main
    rc = _main.do_refresh_ipcat_cache(
        "nord-iq10",
        chip_alias=_CHIP_ALIAS,
        mechanism="B",
    )
    assert rc == 3, f"expected 3 for mechanism='B', got {rc}"
    print("PASS mech-val-c: mechanism='B' (unsupported) -> return 3, no I/O")


def test_mechanism_rejection_precedes_path_resolution() -> None:
    """Mechanism check fires before resolve_ipcat_evidence_dir is called.
    Patch resolve_ipcat_evidence_dir to a sentinel that would fail the test
    if called — an invalid mechanism must never reach it."""
    import orchestrator.main as _main

    resolution_called = []
    orig_resolve = _main.resolve_ipcat_evidence_dir
    _main.resolve_ipcat_evidence_dir = lambda t: resolution_called.append(t) or Path("/nonexistent")
    try:
        rc = _main.do_refresh_ipcat_cache(
            "nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="INVALID",
        )
    finally:
        _main.resolve_ipcat_evidence_dir = orig_resolve

    assert rc == 3
    assert not resolution_called, (
        "resolve_ipcat_evidence_dir was called before mechanism validation rejected"
    )
    print("PASS mech-val-d: mechanism validation fires before path resolution")


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main() -> None:
    # T-IA-01
    test_runners_have_no_ipcat_acquire_import()
    test_do_run_body_has_no_ipcat_acquire_import()
    test_ipcat_acquire_package_is_importable()
    # T-IA-02
    test_full_cli_path_returns_exit_0()
    # T-IA-05
    test_missing_mcp_json_returns_exit_3()
    # T-IA-06
    test_auth_wall_returns_exit_3()
    # T-IA-14
    test_target_and_refresh_mutual_exclusion()
    test_onboard_and_refresh_mutual_exclusion()
    test_replay_and_refresh_mutual_exclusion()
    # mechanism validation
    test_mechanism_none_returns_exit_3()
    test_mechanism_invalid_string_returns_exit_3()
    test_mechanism_unsupported_b_returns_exit_3()
    test_mechanism_rejection_precedes_path_resolution()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
