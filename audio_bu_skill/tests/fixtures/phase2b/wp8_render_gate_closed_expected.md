
## Generation

Phase-2B code-generator fan-in: one entry per artifact class, plus the WP7 post-generation trust verdict. **Diagnostic only** — does not activate the case or write kernel files.

### Per-artifact status

| artifact_class | subject | kind | detail |
|----------------|---------|------|--------|
| codec_stub | codec_stub | GeneratedArtifact | generated/codec_stub/codec.c |
| machine_driver | machine_driver | GeneratorSkipped | gating_row_disagree_on_bus |

### Post-verification (WP7)

Overall verdict: **fail**

| artifact_class | subject | kind | verdict | message |
|----------------|---------|------|---------|---------|
| codec_stub | codec_stub | gate_consistency | fail | gate-consistency: artifact emitted but the following gating rows are CLOSED in source facts: ['T4a.qup.se3'] |
| machine_driver | machine_driver | skip_validity | pass | skip-validity: reason='gating_row_disagree_on_bus' valid; ≥1 cited gate closed in source facts. |

### Contributes-rows FIXMEs

| artifact | row |
|----------|-----|
| codec_stub | T4b/codec.adau1979 (authority_out_of_scope) |

