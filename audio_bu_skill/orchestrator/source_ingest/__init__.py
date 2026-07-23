"""WP-SRC-A source-fact ingestion package.

Populates the source side of cross-verify (pinmux / endpoints / DTS)
that is empty on Nord and Eliza `profile.json` today — the root
cause behind G-3A.7 (three-of-four generators gated closed).

Commit 1 (this): only ``pinmux.derive_pinmux_from_dt`` exists.
Later WP-SRC-A commits add ``SOURCE_UNRESOLVED`` for underivable
inputs and wire ingestion into ``_build_audio_topology`` for
end-to-end integration.

Refs: PHASE3A_IMPLEMENTATION_PLAN.md §4 WP-SRC-A,
      docs/PHASE3_KNOWN_GAPS.md G-3A.7.
"""
