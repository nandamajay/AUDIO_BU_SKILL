
## Generation

Phase-2B code-generator fan-in: one entry per artifact class, plus the WP7 post-generation trust verdict. **Diagnostic only** — does not activate the case or write kernel files.

### Per-artifact status

| artifact_class | subject | kind | detail |
|----------------|---------|------|--------|
| audioreach_topology | audioreach_topology | GeneratedArtifact | generated/audioreach_topology/topo.xml |
| codec_stub | codec_stub | GeneratedArtifact | generated/codec_stub/codec.c |
| dt_scaffolding | dt_scaffolding | GeneratedArtifact | generated/dt_scaffolding/board.dtsi |
| machine_driver | machine_driver | GeneratedArtifact | generated/machine_driver/machine.c |

### Post-verification (WP7)

Overall verdict: **pass**

| artifact_class | subject | kind | verdict | message |
|----------------|---------|------|---------|---------|
| audioreach_topology | audioreach_topology | gate_consistency | pass | gate-consistency: every registered gating row opens in source facts. |
| codec_stub | codec_stub | gate_consistency | pass | gate-consistency: every registered gating row opens in source facts. |
| dt_scaffolding | dt_scaffolding | gate_consistency | pass | gate-consistency: every registered gating row opens in source facts. |
| machine_driver | machine_driver | gate_consistency | pass | gate-consistency: every registered gating row opens in source facts. |

### Contributes-rows FIXMEs

| artifact | row |
|----------|-----|
| codec_stub | T4b/codec.adau1979 (authority_out_of_scope) |
| codec_stub | T4b/codec.pcm1681 (authority_out_of_scope) |

