"""Phase-3A WP-E — Fact Registry error hierarchy.

Every raise-point in the registry package produces one of these exceptions.
Callers can catch the base :class:`RegistryError` to handle "anything the
registry threw" without importing every leaf class.

Design contract (WP_E_FACT_REGISTRY_DESIGN.md §3.1, §3.2, §9):

- ``Registry.load()`` NEVER raises for missing / corrupt / hash-mismatch /
  unsupported-schema / partial-parse conditions — those surface via
  :class:`RegistryStatus`. Only programmer errors escape as
  :class:`RegistryLoadError`.
- :class:`RegistryLockError` is raised when the POSIX advisory lock cannot be
  acquired within the caller-supplied timeout.
- :class:`RegistryWriteError` is raised on I/O failure or invariant violation
  during ``append_provenance`` (write-time). It is also raised when the
  provenance chain would exceed ``MAX_PROVENANCE_CHAIN_LEN`` (§3.2).
"""

from __future__ import annotations


class RegistryError(Exception):
    """Base class for every exception raised by the fact_registry package."""


class RegistryLoadError(RegistryError):
    """Raised only on programmer-level errors from ``Registry.load()``.

    Never raised for missing-file / corrupt / partial / hash-mismatch /
    unsupported-schema conditions — those surface via ``Registry.status``.
    """


class RegistryLockError(RegistryError):
    """Raised when the POSIX advisory write-lock cannot be acquired in time."""


class RegistryWriteError(RegistryError):
    """Raised when a write operation fails or violates an invariant."""


__all__ = [
    "RegistryError",
    "RegistryLoadError",
    "RegistryLockError",
    "RegistryWriteError",
]
