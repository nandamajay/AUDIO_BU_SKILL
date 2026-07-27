"""H-1 audio hardware template projector (data-flow leaf).

This subsystem projects rows already committed to
``gc["cross_verification"]["rows"]`` into two reviewer-oriented artefacts:

  * ``audio_hardware_template.json`` — grouped by entity family
    (board_metadata, codecs, amplifiers, buses, clocks, audio_links).
    Every leaf value is wrapped in a :class:`FactRecord` envelope so the
    reviewer sees value + authority + citations + NCC state in one place.
  * ``gap_manifest.json`` — flattened reviewer view of every NCC /
    NOT_ATTESTED / candidate_derived leaf, keyed by coverage_gap_reason.

**Firewall guarantees (WP-64 sibling):**

  * The projector is a *pure reader*. It does not write
    ``gc["cross_verification"]["rows"]`` (guarded by
    ``test_h1_projector_is_data_flow_leaf.py``).
  * The projector never promotes ``candidate_value`` into the authority
    slot (guarded by ``test_h1_projector_never_promotes_candidate.py``).
  * The projector never issues a ``MATCH``/``PARTIAL_MATCH`` verdict,
    never opens an ``is_open`` gate, and never adds a new authority
    strength (``SCHEMATIC_DIRECT`` is explicitly forbidden).
  * Reasoning-subsystem imports are restricted to
    ``orchestrator.reasoning.crossverify_model`` (the row type only).
"""
