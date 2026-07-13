# KB rule-ID registry (`_index.md`)

The immutable registry of every rule/pattern/distinction ID in the Audio KB. IDs
are **append-mostly and owner-gated**: once published, an ID is never renumbered
or reused. Supersede an entry by setting its status to `deprecated` and pointing
to its replacement — never by deleting or renumbering.

Consistency invariants (checked by `tests/test_kb_value_lint.py`):
- every ID cited anywhere (KB body, ledger `rule_ids`, target evidence) exists here;
- no duplicate IDs;
- every rule/pattern/distinction defined in a KB file has an entry here.

| Rule ID    | File            | One-line summary                                             | Status | Added      | Confirmations |
|------------|-----------------|--------------------------------------------------------------|--------|------------|---------------|
| PROV-001   | provenance.md   | Anti-copy: never substitute a sibling's per-silicon value    | active | 2026-07-13 | 0             |
| PROV-002   | provenance.md   | Authority order: catalog > boot > DT > MISSING               | active | 2026-07-13 | 0             |
| PROV-003   | provenance.md   | Surface routing: value→enumeration, topology→prose           | active | 2026-07-13 | 0             |
| PROV-004   | provenance.md   | Cite-the-attempt: MISSING must record surfaces tried         | active | 2026-07-13 | 0             |
| PROV-P1    | provenance.md   | Missing-with-trail pattern                                    | active | 2026-07-13 | 0             |
| PROV-P2    | provenance.md   | Authority-but-unconfirmed → VERIFY                           | active | 2026-07-13 | 0             |
| PROV-D1    | provenance.md   | Distinction: silicon fact vs board fact vs inference         | active | 2026-07-13 | 0             |
| ADSP-001   | adsp.md         | DSP/PAS base is a silicon fact (PROV-001/002)                | active | 2026-07-13 | 0             |
| ADSP-002   | adsp.md         | Determine power-model class before drafting domains          | active | 2026-07-13 | 0             |
| ADSP-P1    | adsp.md         | Unconfirmed power model → NEEDS_REVIEW                        | active | 2026-07-13 | 0             |
| ADSP-P2    | adsp.md         | Derive compatible by method, never copy a sibling's          | active | 2026-07-13 | 0             |
| ADSP-D1    | adsp.md         | Distinction: DSP image vs register/power facts               | active | 2026-07-13 | 0             |
| ADSP-D2    | adsp.md         | Distinction: power-model class vs domain index               | active | 2026-07-13 | 0             |
| LPASS-001  | lpass.md        | LPASS macro base is a silicon fact (PROV-002)                | active | 2026-07-13 | 0             |
| LPASS-002  | lpass.md        | Macro presence via prose; base never via prose               | active | 2026-07-13 | 0             |
| LPASS-P1   | lpass.md        | DT absence of a macro node ≠ hardware absence                | active | 2026-07-13 | 0             |
| LPASS-D1   | lpass.md        | Distinction: macro presence vs macro base                    | active | 2026-07-13 | 0             |
| AR-001     | audioreach.md   | Flag, don't fabricate: never invent a logical-port macro     | active | 2026-07-13 | 0             |
| AR-002     | audioreach.md   | Port-mapping authority = DSP/firmware owner, not DT          | active | 2026-07-13 | 0             |
| AR-P1      | audioreach.md   | Unmatched interface → NEEDS_REVIEW + escalate                | active | 2026-07-13 | 0             |
| AR-D1      | audioreach.md   | Distinction: placeholder mapping vs confirmed mapping        | active | 2026-07-13 | 0             |
| SWR-001    | soundwire.md    | SoundWire controller base is a silicon fact (PROV-002)       | active | 2026-07-13 | 0             |
| SWR-P1     | soundwire.md    | Missing DT controller node is not a count source             | active | 2026-07-13 | 0             |
| SWR-D1     | soundwire.md    | Distinction (flagship): master count vs board routing        | active | 2026-07-13 | 0             |
| CLK-001    | audio_clocks.md | Anti-interpolation: never copy/interpolate clock rates       | active | 2026-07-13 | 0             |
| CLK-P1     | audio_clocks.md | Prose gives sequences, not rates → rates MISSING             | active | 2026-07-13 | 0             |
| CLK-D1     | audio_clocks.md | Distinction: clock topology vs clock rate                    | active | 2026-07-13 | 0             |
