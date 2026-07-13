# KB entry skeleton (authoring reference — NOT a rule file)

This template defines the mandatory section structure every `references/kb/*.md`
file must follow. It carries no rules of its own; it exists so authors and the
skeleton-conformance check share one source of truth.

Copy the block below when creating a new KB file. Every `##` section header must
be present (a section may say "None yet." but must exist).

```
# KB: <topic>

## Scope
<what class of audio hardware / reasoning this file covers — target-agnostic>

## Rules
<normative always/never statements, each with an immutable ID, e.g. FOO-001>

## Patterns
<recurring situation → recommended handling, each with an ID>

## Distinctions
<category separations that prevent errors, each with a D-suffixed ID, e.g. FOO-D1>

## Provenance
<fact-class → authoritative-source order (defer to provenance.md by ID)>

## Anti-patterns
<named recurring failure modes>

## Anonymized illustrations
<"a target exhibited X" — NO target names, NO values>

## Open questions
<known gaps this KB cannot yet answer>

## Change log
<learn-loop appends: dated, rule ID, N confirmed targets, WARN: on conflict>
```

## Authoring contract (all KB files)

- **FORBIDDEN content (hard lint failure):** any concrete register address/base/
  size, IRQ number, clock rate, instance count, GPIO number, part number,
  SoC-bound compatible string, document ID, or any statement true of exactly one
  target. These are *values* and live only in `targets/<t>/evidence/`.
- **ALLOWED content:** rules, patterns, distinctions, provenance guidance,
  decision procedures, named anti-patterns, and *anonymized* illustrations that
  show why a rule exists without naming a target or quoting its value.
- **Stable IDs:** every rule/pattern/distinction gets an immutable ID
  (`<PREFIX>-<NNN>` for rules/patterns, `<PREFIX>-D<N>` for distinctions),
  registered in `_index.md`. IDs are never renumbered or reused; supersede via a
  `deprecated` status + pointer.
- **Litmus test:** *"Would this still be useful for a future target that does
  not resemble any target seen so far?"* If no → route to target evidence, not
  the KB.
- **Provenance deference:** other files cite `provenance.md` rules by ID rather
  than restating them.
