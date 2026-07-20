# Fact Registry — runtime state directory

This directory holds the **advisory-only** Fact Registry produced and consumed
by `audio_bu_skill/orchestrator/fact_registry/` (WP-E, Phase-3A). It is *not*
part of any generated deliverable: nothing here is promoted into `case.py`,
`case.generated.py`, or any runner output. The registry records **where each
fact came from** (provenance) so that coverage/authority reporting can cite
primary sources — it never feeds values back into a runtime flow.

## What lives here

At run time, one append-only JSON Lines file per target:

- `<target>.json`          — the registry itself (one fact record per line;
                             a `registry_header` line first).
- `<target>.registry.hash` — a sidecar carrying the SHA-256 of `<target>.json`,
                             used to detect out-of-band mutation on load.
- `<target>.lock`          — a transient POSIX advisory lock held only during a
                             write.

Example: a Nord IQ-10 onboarding run would write
`state/fact_registry/nord-iq10.json` plus its `.registry.hash` sidecar.

## Why these are git-ignored

The `.json`, `.registry.hash`, and `.lock` files are **machine-local runtime
state**, regenerated on each run and specific to the operator's evidence set.
They are deliberately excluded from version control (see `.gitignore` here).
Only this `README.md` and the `.gitignore` are checked in, which keeps the
directory present in a fresh clone without committing any run artifacts.

## Format & guarantees (summary)

- **Append-only.** Each observation of a fact appends a new provenance entry;
  earlier entries are never rewritten. The chain is capped at 100 entries.
- **Deterministic serialisation.** Records are sorted by fact key and written
  with stable key ordering, so an unchanged registry re-serialises byte-for-byte.
- **Hash-verified load.** A mismatch between `<target>.json` and its sidecar is
  surfaced as a load status (`HASH_MISMATCH`), never silently trusted.
- **Advisory-only.** The package importing this state must not import from
  `orchestrator.runners`, `orchestrator.main`, or `targets/` (enforced by
  `tests/test_fact_registry_import_isolation.py`).

See `audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md` for the full schema,
status precedence, and write protocol.
