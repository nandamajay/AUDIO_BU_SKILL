"""QGenie/Claude reasoning client + strict environment validation (v1.2).

This is the seam that makes QGenie/Claude the *mandatory* reasoning engine for the
intelligent parts of the workflow. Local Python does orchestration, schema
validation, artifact writing, and fingerprinting; the reasoning (schematic / IPCAT
/ datasheet / kernel analysis, nearest-target selection, codec/topology/power
inference) belongs here, behind ``QGenieReasoningClient``.

**Strict, no silent fallback.** If QGenie cannot run or cannot return valid output,
the client raises ``ReasoningUnavailableError`` with a specific ``.code``. It never
substitutes a local heuristic, never fabricates an analysis. The demoted local
``orchestrator/similarity`` engine is reachable only via the explicit, test-gated
``"local-test"`` engine (see ``get_reasoning_client``), never in production.

Concrete CLI surface (confirmed on this host, qgenie 1.1.13 + claude 2.1.198):
  * ``qgenie doctor --support`` — parseable env/auth/connectivity report (preflight).
  * ``qgenie claude -p <prompt> --output-format json --json-schema <inline JSON>
     --add-dir <kernel> --add-dir <evidence> --permission-mode bypassPermissions
     --allowedTools Read,Grep,Glob,mcp__plugin_qgenie-chat_qgenie-chat__*`` —
     launches Claude Code headless with QGenie endpoint/OAuth injection; the
     ``--json-schema`` flag (given the schema INLINE, not a file path — a path
     makes claude try to JSON-parse the path string itself) forces structured
     JSON output. IPCAT/qgenie-chat MCP is reached via the qgenie-chat plugin's
     own pre-authenticated, auto-managed MCP server — no ``--mcp-config`` is
     passed (that flag creates a second, never-authenticated, anonymous MCP
     server registration instead of using the plugin's already-connected one).
     ``--permission-mode plan`` is architecturally incompatible with headless
     ``-p`` runs (it requires a human to approve each tool call); this client
     uses ``bypassPermissions`` instead, scoped tightly by ``--allowedTools``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import jsonschema

from orchestrator.reasoning.result import ReasoningResult
from orchestrator.reasoning.schemas import ANALYSIS_SCHEMA, ANALYSIS_SCHEMA_VERSION

_DEFAULT_TIMEOUT = 900  # seconds; a hard ceiling on one analysis call.
# The qgenie-chat plugin's real, live MCP tool-name prefix (confirmed via a
# live smoke test against the plugin's auto-managed, pre-authenticated MCP
# server) -- NOT "mcp__qgenie-chat__*", which matches nothing real and was
# the original cause of every IPCAT tool call being silently denied.
_ALLOWED_TOOLS = "Read,Grep,Glob,mcp__plugin_qgenie-chat_qgenie-chat__*"
# Guidance appended to the analysis prompt so the model waits for the
# plugin's MCP server to finish its ~1.3s async connect before attempting any
# IPCAT/qgenie-chat MCP query -- otherwise the very first turn can observe a
# false "no MCP tools available" state (confirmed race, see client.py's
# module docstring history / PLAYBOOK.md).
_MCP_READINESS_GUIDANCE = (
    "Before attempting any IPCAT or qgenie-chat MCP tool call, call the "
    "WaitForMcpServers tool first to ensure MCP servers have finished "
    "connecting. Do this once, at the start, before your first MCP tool use."
)


class ReasoningUnavailableError(Exception):
    """Raised when QGenie/Claude cannot run or cannot produce valid output.

    ``code`` is one of the strict no-fallback codes below; ``details`` carries a
    log-safe, non-confidential summary (argv summary, exit code, stderr tail).
    """

    # -- environment / availability --
    CLI_NOT_FOUND = "QGENIE_CLI_NOT_FOUND"
    ENV_INVALID = "QGENIE_ENV_INVALID"
    AUTH_FAILED = "QGENIE_AUTH_FAILED"
    MCP_UNAVAILABLE = "QGENIE_MCP_UNAVAILABLE"
    # -- analysis call --
    ANALYSIS_TIMEOUT = "QGENIE_ANALYSIS_TIMEOUT"
    ANALYSIS_FAILED = "QGENIE_ANALYSIS_FAILED"
    OUTPUT_UNPARSEABLE = "QGENIE_OUTPUT_UNPARSEABLE"
    OUTPUT_SCHEMA_INVALID = "QGENIE_OUTPUT_SCHEMA_INVALID"
    # -- factory / policy --
    LOCAL_ENGINE_BLOCKED = "LOCAL_ENGINE_BLOCKED"

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ReasoningClient(ABC):
    """A source of structured reasoning. Implementations never mutate on disk."""

    engine_id: str = "abstract"
    model_id: str = ""
    cli_version: str = ""

    @abstractmethod
    def analyze(
        self,
        task_spec: dict[str, Any],
        *,
        json_schema: dict[str, Any],
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> ReasoningResult:
        """Reason over ``task_spec`` and return a schema-validated result."""
        raise NotImplementedError


class QGenieReasoningClient(ReasoningClient):
    """The production reasoning engine: QGenie-launched headless Claude Code.

    ``preflight()`` validates the environment via ``qgenie doctor --support`` and
    must be called (or is called by ``analyze``) before any analysis. ``analyze()``
    builds the argv, runs the subprocess under a hard timeout, and parses +
    re-validates the structured output. Any failure raises
    ``ReasoningUnavailableError`` — there is no fallback.
    """

    engine_id = "qgenie"

    def __init__(
        self,
        *,
        qgenie_bin: str | None = None,
        model: str | None = None,
    ):
        self._qgenie_bin = qgenie_bin  # resolved in preflight if None
        self._model = model
        self._preflighted = False
        # QGENIE_CLI_HOME selects between independently-provisioned QGenie CLI
        # profiles (see module docstring's dual-profile note); captured at
        # construction time since that's the env the call will actually run
        # under. config_root/data_root are filled in once `doctor --support`
        # has been parsed (they're profile facts, not constants).
        self._qgenie_cli_home = os.environ.get("QGENIE_CLI_HOME")
        self._config_root: str | None = None
        self._data_root: str | None = None
        # Coarse progress marker for diagnostics (Task: "capture launch state")
        # — the last preflight/analysis stage completed before any failure.
        self._launch_state = "not_started"

    def _profile_snapshot(self) -> dict[str, Any]:
        return {
            "qgenie_cli_home": self._qgenie_cli_home,
            "config_root": self._config_root,
            "data_root": self._data_root,
        }

    def _mcp_snapshot(self, *, require_ipcat: bool = True) -> dict[str, Any]:
        # IPCAT/qgenie-chat MCP is reached via the plugin's own auto-managed,
        # pre-authenticated MCP server -- there is no local config file to
        # check for existence; readiness is validated live by the analysis
        # call itself (guided by _MCP_READINESS_GUIDANCE in the prompt).
        return {
            "require_ipcat": require_ipcat,
            "allowed_tools": _ALLOWED_TOOLS,
        }

    def _diagnostics(self, *, require_ipcat: bool = True) -> dict[str, Any]:
        """Everything reasoning_error.json needs beyond the raw failure: what
        stage we got to, which QGenie profile answered, and IPCAT MCP state."""
        return {
            "launch_state": self._launch_state,
            "profile": self._profile_snapshot(),
            "mcp_state": self._mcp_snapshot(require_ipcat=require_ipcat),
        }

    @property
    def qgenie_cli_home(self) -> str | None:
        """The QGENIE_CLI_HOME in effect for this client (profile selector)."""
        return self._qgenie_cli_home

    @property
    def config_root(self) -> str | None:
        """The profile's config_root, populated after a successful preflight."""
        return self._config_root

    @property
    def data_root(self) -> str | None:
        """The profile's data_root, populated after a successful preflight."""
        return self._data_root

    # ----------------------------------------------------------------- #
    # env validation
    # ----------------------------------------------------------------- #
    def _resolve_bin(self) -> str:
        found = self._qgenie_bin or shutil.which("qgenie")
        if not found:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.CLI_NOT_FOUND,
                "the `qgenie` CLI was not found on PATH",
                {**self._diagnostics()},
            )
        self._launch_state = "cli_resolved"
        return found

    def preflight(self, *, require_ipcat: bool = True, timeout: int = 60) -> None:
        """Validate env/auth/connectivity via `qgenie doctor --support`.

        Raises ``ReasoningUnavailableError`` on any failure; on success records
        ``cli_version``/``model_id`` and marks the client preflighted. Idempotent.
        """
        qgenie_bin = self._resolve_bin()
        try:
            proc = subprocess.run(
                [qgenie_bin, "doctor", "--support"],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.ENV_INVALID,
                "`qgenie doctor --support` timed out",
                {"timeout": timeout, **self._diagnostics(require_ipcat=require_ipcat)},
            ) from exc
        except OSError as exc:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.CLI_NOT_FOUND,
                f"could not execute `qgenie`: {exc}",
                {**self._diagnostics(require_ipcat=require_ipcat)},
            ) from exc

        report = proc.stdout or ""
        if proc.returncode != 0:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.ENV_INVALID,
                "`qgenie doctor --support` exited non-zero",
                {"exit_code": proc.returncode, "stderr_tail": _tail(proc.stderr),
                 **self._diagnostics(require_ipcat=require_ipcat)},
            )
        self._launch_state = "doctor_ran"

        parsed = _parse_doctor_report(report)
        # profile facts, captured regardless of what fails below — the whole
        # point of Task #32's "capture profile information" is to know WHICH
        # profile answered, even on failure.
        self._config_root = parsed.get("config_root")
        self._data_root = parsed.get("data_root")

        # auth must be configured (startswith, not substring — "not_configured"
        # contains "configured" as a substring and must NOT pass this gate)
        auth = parsed.get("auth", "")
        if not auth.startswith("configured"):
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.AUTH_FAILED,
                f"QGenie auth is not configured (doctor: auth={auth!r})",
                {"auth": auth, **self._diagnostics(require_ipcat=require_ipcat)},
            )
        self._launch_state = "auth_checked"

        # the claude harness must be launch_ready (that is the reasoning entrypoint)
        claude_status = parsed.get("harness_claude", "")
        if "launch_ready" not in claude_status:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.ENV_INVALID,
                f"the claude harness is not launch_ready (doctor: {claude_status!r})",
                {"harness_claude": claude_status, **self._diagnostics(require_ipcat=require_ipcat)},
            )
        self._launch_state = "claude_ready_checked"

        # connectivity must be healthy
        connectivity = parsed.get("connectivity", "")
        if connectivity and "reachable" not in connectivity and "healthy" not in connectivity:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.AUTH_FAILED,
                f"QGenie services are not reachable (doctor: {connectivity!r})",
                {"connectivity": connectivity, **self._diagnostics(require_ipcat=require_ipcat)},
            )
        self._launch_state = "connectivity_checked"

        # IPCAT/qgenie-chat MCP has no local config to check for existence --
        # it's the plugin's own auto-managed, pre-authenticated server; its
        # actual readiness is validated live by the analysis call, not here.
        self._launch_state = "ipcat_mcp_checked"

        self.cli_version = parsed.get("qgenie_version", "")
        self.model_id = self._model or parsed.get("harness_claude_version", "")
        self._preflighted = True
        self._launch_state = "preflighted"

    # ----------------------------------------------------------------- #
    # analysis
    # ----------------------------------------------------------------- #
    def analyze(
        self,
        task_spec: dict[str, Any],
        *,
        json_schema: dict[str, Any] = ANALYSIS_SCHEMA,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> ReasoningResult:
        require_ipcat = bool(task_spec.get("evidence", {}).get("ipcat_mcp"))
        if not self._preflighted:
            self.preflight(require_ipcat=require_ipcat)
        qgenie_bin = self._resolve_bin()

        prompt = build_prompt(task_spec)

        # `claude --json-schema` takes the schema INLINE (a JSON string), not a
        # file path -- passing a path makes claude try to json.loads() the path
        # string itself and fail with "Unrecognized token '/'".
        argv = [
            qgenie_bin, "claude", "-p", prompt,
            "--output-format", "json",
            "--json-schema", json.dumps(json_schema),
            "--permission-mode", "bypassPermissions",
            "--allowedTools", _ALLOWED_TOOLS,
        ]
        for add_dir in _add_dirs(task_spec):
            argv += ["--add-dir", add_dir]
        if self._model:
            argv += ["--model", self._model]

        argv_fingerprint = _argv_fingerprint(argv, prompt)

        self._launch_state = "analysis_launched"
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.ANALYSIS_TIMEOUT,
                f"QGenie analysis exceeded the {timeout}s timeout",
                {"argv_summary": _argv_summary(argv), "timeout": timeout,
                 **self._diagnostics(require_ipcat=require_ipcat)},
            ) from exc
        except OSError as exc:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.ANALYSIS_FAILED,
                f"could not launch QGenie analysis: {exc}",
                {"argv_summary": _argv_summary(argv), **self._diagnostics(require_ipcat=require_ipcat)},
            ) from exc
        self._launch_state = "analysis_process_exited"

        if proc.returncode != 0:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.ANALYSIS_FAILED,
                "QGenie analysis exited non-zero",
                {"argv_summary": _argv_summary(argv),
                 "exit_code": proc.returncode,
                 "stderr_tail": _tail(proc.stderr),
                 **self._diagnostics(require_ipcat=require_ipcat)},
            )

        raw_text = proc.stdout or ""
        parsed = _extract_analysis_json(raw_text, argv_summary=_argv_summary(argv))
        _validate_analysis(parsed, argv_summary=_argv_summary(argv))
        self._launch_state = "analysis_completed"

        return ReasoningResult(
            parsed=parsed,
            raw_text=raw_text,
            engine_id=self.engine_id,
            model_id=self.model_id,
            cli_version=self.cli_version,
            schema_version=ANALYSIS_SCHEMA_VERSION,
            argv_fingerprint=argv_fingerprint,
        )


# --------------------------------------------------------------------------- #
# prompt + argv helpers
# --------------------------------------------------------------------------- #
def build_prompt(task_spec: dict[str, Any]) -> str:
    """Render the analysis instruction. Sends paths/refs only — never file bytes.

    The model is directed to read the kernel tree + evidence files itself (via the
    Read/Grep/Glob tools it was granted) and IPCAT via the qgenie-chat MCP, then
    return JSON matching the schema it was given by ``--json-schema``. When IPCAT
    MCP evidence is requested, ``_MCP_READINESS_GUIDANCE`` is prepended so the
    model waits out the MCP server's async connect before its first MCP call.
    """
    mcp_guidance = ""
    if task_spec.get("evidence", {}).get("ipcat_mcp"):
        mcp_guidance = _MCP_READINESS_GUIDANCE + "\n\n"
    return (
        mcp_guidance +
        "You are an audio bring-up analyst. Analyze the evidence for a new SoC "
        "audio bring-up target and return ONLY the JSON object required by the "
        "provided output schema — no prose outside the JSON.\n\n"
        "Read the kernel tree and the evidence files listed below yourself (use "
        "the Read/Grep/Glob tools), and query IPCAT via the qgenie-chat MCP tools "
        "when available. Identify: the SoC/board identity; codecs and amplifiers "
        "(part numbers, e.g. WSA884x); microphones and speakers; audio buses; "
        "SoundWire presence and master count; the LPASS/ADSP/AudioReach/GPR/APM "
        "stack; and the power model (rpmhpd vs. SCMI). Rank the nearest existing "
        "targets with a rationale. List any missing evidence.\n\n"
        "Every finding MUST carry per-field confidence (0..1) and citations "
        "(evidence file path, IPCAT doc id, or kernel file path). NEVER finalize "
        "the power model: set power_model.needs_review = true always. If evidence "
        "is insufficient to identify something, say so in missing_evidence and "
        "lower the confidence rather than guessing.\n\n"
        "TASK SPEC (paths and references only):\n"
        f"{json.dumps(task_spec, indent=2, sort_keys=True)}\n"
    )


def _add_dirs(task_spec: dict[str, Any]) -> list[str]:
    """Directories the model is allowed to read: kernel tree + evidence roots."""
    dirs: list[str] = []
    kernel_path = (task_spec.get("kernel") or {}).get("path")
    if kernel_path:
        dirs.append(str(kernel_path))
    for group in ("offline", "ipcat"):
        for f in (task_spec.get("evidence") or {}).get(group, []) or []:
            parent = str(Path(f).parent)
            if parent not in dirs:
                dirs.append(parent)
    return dirs


def _argv_fingerprint(argv: list[str], prompt: str) -> str:
    """Stable digest of the call shape (argv with the long prompt elided)."""
    shape = [a if a != prompt else "<prompt>" for a in argv]
    blob = json.dumps({"argv": shape, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()},
                      sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _argv_summary(argv: list[str]) -> list[str]:
    """Log-safe argv: drop the (possibly long / sensitive) prompt payload."""
    out: list[str] = []
    skip_next = False
    for i, a in enumerate(argv):
        if skip_next:
            out.append("<prompt>")
            skip_next = False
            continue
        out.append(a)
        if a == "-p":
            skip_next = True
    return out


def _tail(text: str | None, limit: int = 800) -> str:
    if not text:
        return ""
    return text[-limit:]


# --------------------------------------------------------------------------- #
# doctor report parsing
# --------------------------------------------------------------------------- #
def _parse_doctor_report(report: str) -> dict[str, str]:
    """Extract the fields we gate on from `qgenie doctor --support` plaintext.

    Format (confirmed): a ``CLI`` block with ``qgenie_version:``, ``auth:``,
    ``config_root:``, and ``data_root:`` lines, a ``Harnesses`` block with a
    ``claude:`` line carrying comma-separated readiness flags + ``version=...``,
    and a ``Connectivity`` block whose body line reads e.g. ``all services
    reachable``. ``config_root``/``data_root`` are profile facts (see the
    QGENIE_CLI_HOME dual-profile note in the module docstring) — capturing them
    is how a fingerprint/diagnostic records WHICH profile answered a given call.
    """
    out: dict[str, str] = {}
    section = ""
    for raw in report.splitlines():
        line = raw.strip()
        if not line:
            continue
        # section headers are unindented, single words
        if not raw.startswith(" ") and ":" not in line:
            section = line.lower()
            continue
        if line.startswith("qgenie_version:"):
            out["qgenie_version"] = line.split(":", 1)[1].strip()
        elif line.startswith("auth:"):
            out["auth"] = line.split(":", 1)[1].strip()
        elif line.startswith("config_root:"):
            out["config_root"] = line.split(":", 1)[1].strip()
        elif line.startswith("data_root:"):
            out["data_root"] = line.split(":", 1)[1].strip()
        elif line.startswith("claude:"):
            status = line.split(":", 1)[1].strip()
            out["harness_claude"] = status
            for tok in status.split(","):
                tok = tok.strip()
                if tok.startswith("version="):
                    out["harness_claude_version"] = tok.split("=", 1)[1].strip()
        elif section == "connectivity":
            # the connectivity body line, e.g. "all services reachable"
            out.setdefault("connectivity", line)
    return out


# --------------------------------------------------------------------------- #
# output extraction + validation
# --------------------------------------------------------------------------- #
def _extract_analysis_json(raw_text: str, *, argv_summary: list[str]) -> dict[str, Any]:
    """Parse the analysis object out of `claude --output-format json` stdout.

    Handles two shapes: (a) the claude envelope ``{"type": ..., "result": "<json
    string or object>"}`` — extract ``result``; (b) the analysis object directly.
    Raises OUTPUT_UNPARSEABLE if nothing yields valid JSON.
    """
    text = (raw_text or "").strip()
    if not text:
        raise ReasoningUnavailableError(
            ReasoningUnavailableError.OUTPUT_UNPARSEABLE,
            "QGenie returned empty stdout",
            {"argv_summary": argv_summary},
        )
    try:
        top = json.loads(text)
    except ValueError as exc:
        raise ReasoningUnavailableError(
            ReasoningUnavailableError.OUTPUT_UNPARSEABLE,
            "QGenie stdout was not valid JSON",
            {"argv_summary": argv_summary, "stdout_tail": _tail(text)},
        ) from exc

    # claude envelope: pull out .result (may itself be a JSON string or an object)
    candidate: Any = top
    if isinstance(top, dict) and "result" in top and not _looks_like_analysis(top):
        candidate = top["result"]
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except ValueError as exc:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.OUTPUT_UNPARSEABLE,
                "QGenie result field was not valid JSON",
                {"argv_summary": argv_summary, "result_tail": _tail(candidate)},
            ) from exc

    if not isinstance(candidate, dict):
        raise ReasoningUnavailableError(
            ReasoningUnavailableError.OUTPUT_UNPARSEABLE,
            "QGenie output did not contain a JSON object",
            {"argv_summary": argv_summary},
        )
    return candidate


def _looks_like_analysis(obj: dict[str, Any]) -> bool:
    """Heuristic: is this dict already the analysis (not the claude envelope)?"""
    return "soc" in obj and "codecs" in obj and "power_model" in obj


def _validate_analysis(parsed: dict[str, Any], *, argv_summary: list[str]) -> None:
    try:
        jsonschema.validate(instance=parsed, schema=ANALYSIS_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ReasoningUnavailableError(
            ReasoningUnavailableError.OUTPUT_SCHEMA_INVALID,
            f"QGenie output failed ANALYSIS_SCHEMA: {exc.message}",
            {"argv_summary": argv_summary, "path": list(exc.absolute_path)},
        ) from exc


# --------------------------------------------------------------------------- #
# factory — strict, no silent local fallback
# --------------------------------------------------------------------------- #
def get_reasoning_client(
    engine: str = "qgenie",
    *,
    test_mode: bool = False,
    **kwargs: Any,
) -> ReasoningClient:
    """Return the reasoning client for ``engine``. No silent fallback to local.

    - ``"qgenie"`` (default) → a ``QGenieReasoningClient`` (call ``preflight()`` or
      let ``analyze()`` do it).
    - ``"local-test"`` → the demoted local comparator, but ONLY when
      ``test_mode=True``; otherwise raises ``LOCAL_ENGINE_BLOCKED``. Even then it
      stamps ``engine_id="local-test"`` so it can never be mistaken for production.
    - any other id → raises ``ENV_INVALID`` (we never guess an engine).
    """
    if engine in ("qgenie", "", None):
        return QGenieReasoningClient(**kwargs)
    if engine == "local-test":
        if not test_mode:
            raise ReasoningUnavailableError(
                ReasoningUnavailableError.LOCAL_ENGINE_BLOCKED,
                "the local-test engine is blocked in production; pass --test-mode to use it",
                {"engine": engine},
            )
        from orchestrator.reasoning.local_test import LocalTestReasoningClient
        return LocalTestReasoningClient(**kwargs)
    raise ReasoningUnavailableError(
        ReasoningUnavailableError.ENV_INVALID,
        f"unknown reasoning engine {engine!r} (expected 'qgenie' or 'local-test')",
        {"engine": engine},
    )
