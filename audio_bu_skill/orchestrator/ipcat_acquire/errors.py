"""WP-IPCAT-A C1 — acquisition error hierarchy, status enum, exit contract.

This module is **inert**: importing it opens no socket, reads no file, and has
no side effects. It is not imported by any existing runner, by ``main.py``, or
by ``targets/`` — the acquisition package is reachable only from the (C2) CLI
dispatch that does not yet exist.

Contents:

- :class:`AcquireError` — base for every exception the package raises, plus the
  leaf classes for the transport / auth / write failure modes.
- :class:`AcquireStatus` — the outcome enum from design §4.2.
- :func:`exit_code_for` — the status → process exit-code contract (§4.2:
  ``OK`` / ``OK_NOOP`` / ``PLANNED`` → 0; ``UNRESOLVED`` / ``CAPPED_SEARCH`` →
  2; ``AUTH_REQUIRED`` / ``TRANSPORT_ERROR`` / ``WRITE_ERROR`` → 3). The mapping
  lives here, but nothing in C1 calls ``sys.exit`` — that is C2's concern inside
  ``do_refresh_ipcat_cache``.
- :func:`classify_error` — reduce any caught exception to a **redacted category
  label** (the exception *class name*, never its message, never a traceback,
  never token/header material). Carried over from the probe's hardened
  ``_classify_error`` discipline (design §4.2).

Design contract (docs/WP_IPCAT_A_ACQUISITION_DESIGN.md §4.2):
    Every network exception is caught and mapped to a redacted category label.
    ``acquire_to_cache`` never lets a raw traceback or credential material
    escape; failures surface as an :class:`AcquireStatus` on an
    ``AcquireResult``.
"""

from __future__ import annotations

from enum import Enum


class AcquireError(Exception):
    """Base class for every exception raised by the ipcat_acquire package."""


class AcquireAuthError(AcquireError):
    """Raised when the two-layer auth wall (W2/D3) is hit; no bytes written."""


class AcquireTransportError(AcquireError):
    """Raised on TLS / DNS / connect / timeout during a live session."""


class AcquireWriteError(AcquireError):
    """Raised on lock timeout or disk error during atomic publish.

    When raised, the *old* cache is left byte-identical (design §4.2 / §4.3):
    the failure happens before any ``os.replace`` touches a live name, or the
    publish is abandoned mid-flight with provenance-last ordering protecting the
    reader.
    """


class AcquireResolveError(AcquireError):
    """Raised when the chip alias cannot be resolved / is ambiguous."""


class AcquireStatus(str, Enum):
    """Outcome of an acquisition attempt (design §4.2).

    Subclasses ``str`` so a status serialises to its own name in JSON without a
    custom encoder and compares equal to that name.
    """

    OK = "OK"
    OK_NOOP = "OK_NOOP"
    PLANNED = "PLANNED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNRESOLVED = "UNRESOLVED"
    CAPPED_SEARCH = "CAPPED_SEARCH"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    WRITE_ERROR = "WRITE_ERROR"


# Status → process exit code (design §4.2). Kept as a frozen mapping so it is
# a single source of truth; C2's dispatch reads it, C1 only asserts it.
_EXIT_CODE_BY_STATUS: dict[AcquireStatus, int] = {
    AcquireStatus.OK: 0,
    AcquireStatus.OK_NOOP: 0,
    AcquireStatus.PLANNED: 0,
    AcquireStatus.UNRESOLVED: 2,
    AcquireStatus.CAPPED_SEARCH: 2,
    AcquireStatus.AUTH_REQUIRED: 3,
    AcquireStatus.TRANSPORT_ERROR: 3,
    AcquireStatus.WRITE_ERROR: 3,
}


def exit_code_for(status: AcquireStatus) -> int:
    """Return the process exit code for ``status`` per the design §4.2 contract.

    Raises :class:`KeyError` on an unknown status — a programmer error, not a
    runtime condition, so it is intentionally not swallowed.
    """
    return _EXIT_CODE_BY_STATUS[status]


def classify_error(exc: BaseException) -> str:
    """Reduce ``exc`` to a redacted category label: its class name only.

    Never returns the exception message, arguments, a traceback, or any
    token/header material — only ``type(exc).__name__``. This is the sole
    channel by which a caught exception is described to the operator, so it must
    not leak. (Design §4.2, mirroring the probe's ``_classify_error``.)
    """
    return type(exc).__name__


__all__ = [
    "AcquireError",
    "AcquireAuthError",
    "AcquireTransportError",
    "AcquireWriteError",
    "AcquireResolveError",
    "AcquireStatus",
    "exit_code_for",
    "classify_error",
]
