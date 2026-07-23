"""WP-SRC-A2 red baseline: kernel-DT reader plumbing.

Test-first per PHASE3A_IMPLEMENTATION_PLAN.md §5a. This module lands
the failing contract for the kernel-DT reader that populates
``analysis["dt"]`` from ``--kernel-source`` on real ``--onboard`` runs.
The reader implementation ships in a separate commit — this file MUST
land red on its own so the red→green transition is a single-commit
review boundary.

Contract pinned by WP-SRC-A2 (PHASE3A_IMPLEMENTATION_PLAN.md §4
WP-SRC-A2, docs/PHASE3_KNOWN_GAPS.md G-3A.9):

  * T-SRC-A2-1: ``read_dt_pinctrl(kernel_source_path, target)`` exists
    in ``orchestrator.source_ingest.dt_reader`` and returns a dict
    whose ``["pinctrl"]`` shape is directly consumable by
    ``derive_pinmux_from_dt`` — i.e. after reading a Nord kernel tree
    the pipeline ``read_dt_pinctrl(...) → derive_pinmux_from_dt``
    yields a non-empty ``list[PinmuxFact]``, NOT ``SOURCE_UNRESOLVED``.
  * T-SRC-A2-2: integration — after ``--onboard nord-iq10
    --kernel-source ./linux-nord/``, ``profile.audio_topology.pinmux``
    is a non-empty ``list``, each entry's ``name`` field begins with
    ``"gpio.i2s."``, and no entry is the literal string
    ``"SOURCE_UNRESOLVED"``. This is the north-star-adjacent proof
    that the DT-plumbing gap G-3A.9 is closed on real Nord.
  * T-SRC-A2-3: missing / malformed kernel source (nonexistent path,
    non-directory, empty tree, unparseable dtsi) → ``read_dt_pinctrl``
    returns an empty ``{}`` dict — the downstream
    ``derive_pinmux_from_dt`` then returns the ``SOURCE_UNRESOLVED``
    bare-singleton sentinel, and the wiring emits the literal
    ``"SOURCE_UNRESOLVED"`` string at the JSON boundary. This is the
    "A1 behavior unchanged when A2 fails" invariant.
  * T-SRC-A2-4: determinism — two invocations of
    ``read_dt_pinctrl`` on the same kernel tree produce
    byte-identical dicts under ``json.dumps(..., sort_keys=True)``.
    Mirrors ``crossverify_collector._canonical_json_bytes`` and the
    T-SRC-A-4 discipline enforced on the derivation half.

Failure discipline (§5a): each test guards its import in
``try / except ImportError`` and raises ``AssertionError`` naming
the exact missing surface (module, function, or attribute). This
ensures the red-state pytest output names the T-SRC-A2-N test AND
the missing symbol in one line, mirroring the WP-SRC-A1 idiom in
``tests/test_source_ingest_pinmux.py``.

Explicitly out of scope for this red-baseline commit:
  * Any implementation of ``dt_reader`` — that ships in the follow-up
    green commit.
  * Any change to ``_build_audio_topology`` or the onboarding runner
    wiring — the T-SRC-A2-2 integration test drives that in the
    green commit.
  * ``codec_driver_porting`` — G-3A.8, deferred out-of-band.
  * QUP endpoint derivation — WP-SRC-B territory.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_source_ingest_dt_reader``
or ``cd audio_bu_skill && python3 -m pytest tests/test_source_ingest_dt_reader.py -v``.

Signed-off-by: Ajay Kumar Nandam <ajayn@qti.qualcomm.com>
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Fixtures — synthetic sa8775p / Nord I2S8 kernel tree
# ---------------------------------------------------------------------------


_NORD_I2S8_DTSI = """\
&tlmm {
\ti2s8_default: i2s8-default-state {
\t\tmclk-pins {
\t\t\tpins = "gpio147";
\t\t\tfunction = "i2s8";
\t\t\tdrive-strength = <8>;
\t\t\tbias-disable;
\t\t};

\t\tsclk-pins {
\t\t\tpins = "gpio148";
\t\t\tfunction = "i2s8";
\t\t\tdrive-strength = <8>;
\t\t\tbias-disable;
\t\t};

\t\tws-pins {
\t\t\tpins = "gpio149";
\t\t\tfunction = "i2s8";
\t\t\tdrive-strength = <8>;
\t\t\tbias-disable;
\t\t};

\t\tdata-pins {
\t\t\tpins = "gpio150";
\t\t\tfunction = "i2s8";
\t\t\tdrive-strength = <8>;
\t\t\tbias-disable;
\t\t};
\t};
};
"""


def _write_synthetic_nord_tree(root: Path) -> Path:
    """Materialise a minimal sa8775p / Nord DT tree at ``root``.

    Only the directories and files the reader is contracted to walk
    are created. This mirrors the real ``linux-nord`` layout at
    ``arch/arm64/boot/dts/qcom/`` closely enough to exercise the
    reader end-to-end but keeps the fixture under a hundred lines.
    """
    dts_dir = root / "arch" / "arm64" / "boot" / "dts" / "qcom"
    dts_dir.mkdir(parents=True, exist_ok=True)
    (dts_dir / "sa8775p-nord-iq10.dtsi").write_text(_NORD_I2S8_DTSI, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# T-SRC-A2-1: reader function exists, shape consumable by derive_pinmux
# ---------------------------------------------------------------------------


class TestReadDtPinctrlContract(unittest.TestCase):
    """T-SRC-A2-1: reader exists and its output composes with A1."""

    def test_read_dt_pinctrl_shape_composes_with_derive_pinmux(self) -> None:
        try:
            from orchestrator.source_ingest.dt_reader import read_dt_pinctrl
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-A2-1: expected `read_dt_pinctrl(kernel_source_path, target) "
                "-> dict` in `orchestrator.source_ingest.dt_reader`. This module "
                "does not exist yet — WP-SRC-A2 red baseline. The reader must "
                "return a dict whose `['pinctrl']` shape is directly consumable "
                "by `orchestrator.source_ingest.pinmux.derive_pinmux_from_dt`, "
                "so that on real Nord `read_dt_pinctrl(...) → derive_pinmux` "
                f"yields a non-empty `list[PinmuxFact]`. ImportError: {exc}"
            ) from exc

        try:
            from orchestrator.source_ingest.pinmux import derive_pinmux_from_dt
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-A2-1: prerequisite import of `derive_pinmux_from_dt` "
                "from `orchestrator.source_ingest.pinmux` failed — WP-SRC-A1 "
                f"must land before A2 can be exercised. ImportError: {exc}"
            ) from exc

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_synthetic_nord_tree(Path(tmp))
            dt = read_dt_pinctrl(str(root), "nord-iq10")

            if not isinstance(dt, dict):
                raise AssertionError(
                    "T-SRC-A2-1: read_dt_pinctrl must return a `dict` "
                    f"(got {type(dt).__name__}). The A1 derivation function "
                    "consumes `dt['pinctrl']` — the reader owes it a dict."
                )
            pinctrl = dt.get("pinctrl")
            if not isinstance(pinctrl, dict) or not pinctrl:
                raise AssertionError(
                    "T-SRC-A2-1: read_dt_pinctrl must populate a non-empty "
                    "`['pinctrl']` dict when the kernel tree carries I2S8 "
                    f"groups. Got: {pinctrl!r}."
                )

            facts = derive_pinmux_from_dt(dt)
            if not isinstance(facts, list) or not facts:
                raise AssertionError(
                    "T-SRC-A2-1: reader output must compose with "
                    "derive_pinmux_from_dt — the composed pipeline must "
                    "yield a non-empty `list[PinmuxFact]` on real Nord, "
                    f"not `{facts!r}`."
                )
            for f in facts:
                name = getattr(f, "name", None)
                if not isinstance(name, str) or not name.startswith("gpio.i2s."):
                    raise AssertionError(
                        "T-SRC-A2-1: every emitted fact must carry a "
                        f"`gpio.i2s.*` name — got {name!r}."
                    )


# ---------------------------------------------------------------------------
# T-SRC-A2-2: integration — profile.audio_topology.pinmux is real on Nord
# ---------------------------------------------------------------------------


class TestOnboardIntegrationPinmuxNonEmpty(unittest.TestCase):
    """T-SRC-A2-2: --onboard nord-iq10 --kernel-source populates pinmux."""

    def test_onboard_nord_iq10_yields_non_empty_pinmux(self) -> None:
        try:
            from orchestrator.runners.target_onboarding_runner import (
                _build_audio_topology,
            )
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-A2-2: expected `_build_audio_topology` in "
                "`orchestrator.runners.target_onboarding_runner`. WP-SRC-A2 "
                "must wire `analysis['dt']` from `read_dt_pinctrl` output "
                f"through this function. ImportError: {exc}"
            ) from exc

        try:
            from orchestrator.source_ingest.dt_reader import read_dt_pinctrl
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-A2-2: expected `read_dt_pinctrl` in "
                "`orchestrator.source_ingest.dt_reader` — the reader whose "
                "output must be plumbed into `analysis['dt']` on real "
                f"`--onboard` runs. ImportError: {exc}"
            ) from exc

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_synthetic_nord_tree(Path(tmp))
            dt = read_dt_pinctrl(str(root), "nord-iq10")

            analysis: dict[str, Any] = {"dt": dt}
            try:
                topology = _build_audio_topology(analysis=analysis)
            except TypeError as exc:
                raise AssertionError(
                    "T-SRC-A2-2: _build_audio_topology signature must accept "
                    "an `analysis` mapping carrying `analysis['dt']`. The "
                    "WP-SRC-A2 wiring commit is expected to plumb "
                    "`read_dt_pinctrl` output into that key on the real "
                    f"onboarding path. TypeError: {exc}"
                ) from exc

            pinmux = topology.get("pinmux") if isinstance(topology, dict) else None
            if pinmux == "SOURCE_UNRESOLVED":
                raise AssertionError(
                    "T-SRC-A2-2: profile.audio_topology.pinmux is the "
                    "literal 'SOURCE_UNRESOLVED' string — WP-SRC-A2 wiring "
                    "did not populate `analysis['dt']` with reader output "
                    "on the real onboarding path. G-3A.9 still open."
                )
            if not isinstance(pinmux, list) or not pinmux:
                raise AssertionError(
                    "T-SRC-A2-2: profile.audio_topology.pinmux must be a "
                    f"non-empty list; got {pinmux!r}."
                )
            for entry in pinmux:
                if not isinstance(entry, dict):
                    raise AssertionError(
                        "T-SRC-A2-2: each pinmux entry must be a dict; "
                        f"got {type(entry).__name__}."
                    )
                name = entry.get("name")
                if not isinstance(name, str) or not name.startswith("gpio.i2s."):
                    raise AssertionError(
                        "T-SRC-A2-2: each pinmux entry must have a "
                        f"`gpio.i2s.*` name; got {name!r}."
                    )


# ---------------------------------------------------------------------------
# T-SRC-A2-3: missing/malformed kernel source → downstream SOURCE_UNRESOLVED
# ---------------------------------------------------------------------------


class TestReadDtPinctrlMissingSource(unittest.TestCase):
    """T-SRC-A2-3: no readable DT → {} → downstream SOURCE_UNRESOLVED."""

    def test_missing_or_malformed_kernel_source_returns_empty_dict(self) -> None:
        try:
            from orchestrator.source_ingest.dt_reader import read_dt_pinctrl
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-A2-3: expected `read_dt_pinctrl` in "
                "`orchestrator.source_ingest.dt_reader` — the reader that "
                "must return `{}` on missing / malformed kernel source so "
                "the downstream A1 sentinel path is preserved. "
                f"ImportError: {exc}"
            ) from exc

        try:
            from orchestrator.source_ingest.pinmux import (
                SOURCE_UNRESOLVED,
                derive_pinmux_from_dt,
            )
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-A2-3: prerequisite imports of `SOURCE_UNRESOLVED` and "
                "`derive_pinmux_from_dt` from `orchestrator.source_ingest.pinmux` "
                f"failed — WP-SRC-A1 must land before A2 can be exercised. "
                f"ImportError: {exc}"
            ) from exc

        with tempfile.TemporaryDirectory() as tmp:
            missing_root = str(Path(tmp) / "does_not_exist")
            result_missing = read_dt_pinctrl(missing_root, "nord-iq10")
            if result_missing != {}:
                raise AssertionError(
                    "T-SRC-A2-3: missing kernel_source_path must yield `{}`, "
                    f"not {result_missing!r}. The A1 behavior (return "
                    "SOURCE_UNRESOLVED on empty dt) must be preserved when "
                    "A2 has no source to read."
                )
            if derive_pinmux_from_dt(result_missing) is not SOURCE_UNRESOLVED:
                raise AssertionError(
                    "T-SRC-A2-3: derive_pinmux_from_dt({}) must return the "
                    "bare `SOURCE_UNRESOLVED` singleton (identity), so the "
                    "downstream JSON boundary emits the literal string."
                )

        with tempfile.TemporaryDirectory() as tmp:
            empty_root = Path(tmp) / "empty_tree"
            empty_root.mkdir()
            result_empty = read_dt_pinctrl(str(empty_root), "nord-iq10")
            if result_empty != {}:
                raise AssertionError(
                    "T-SRC-A2-3: empty kernel tree must yield `{}`, "
                    f"not {result_empty!r}."
                )
            if derive_pinmux_from_dt(result_empty) is not SOURCE_UNRESOLVED:
                raise AssertionError(
                    "T-SRC-A2-3: derive_pinmux_from_dt on empty-tree reader "
                    "output must return SOURCE_UNRESOLVED (identity)."
                )

        with tempfile.TemporaryDirectory() as tmp:
            garbled = Path(tmp) / "garbled"
            (garbled / "arch" / "arm64" / "boot" / "dts" / "qcom").mkdir(parents=True)
            (garbled / "arch" / "arm64" / "boot" / "dts" / "qcom" / "sa8775p-nord-iq10.dtsi").write_text(
                "not a valid dtsi { { { unbalanced", encoding="utf-8"
            )
            result_garbled = read_dt_pinctrl(str(garbled), "nord-iq10")
            if not isinstance(result_garbled, dict):
                raise AssertionError(
                    "T-SRC-A2-3: malformed dtsi must yield a dict (empty "
                    f"or with no derivable pinctrl); got {type(result_garbled).__name__}."
                )
            if derive_pinmux_from_dt(result_garbled) is not SOURCE_UNRESOLVED:
                raise AssertionError(
                    "T-SRC-A2-3: derive_pinmux_from_dt on garbled-dtsi reader "
                    "output must return SOURCE_UNRESOLVED (identity)."
                )


# ---------------------------------------------------------------------------
# T-SRC-A2-4: determinism — two reads of the same tree are byte-identical
# ---------------------------------------------------------------------------


class TestReadDtPinctrlDeterminism(unittest.TestCase):
    """T-SRC-A2-4: byte-identical output for byte-identical input."""

    def test_two_reads_of_same_tree_are_byte_identical(self) -> None:
        try:
            from orchestrator.source_ingest.dt_reader import read_dt_pinctrl
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-A2-4: expected `read_dt_pinctrl` in "
                "`orchestrator.source_ingest.dt_reader` — the reader that "
                "must produce byte-identical dicts across invocations on "
                f"the same kernel tree. ImportError: {exc}"
            ) from exc

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_synthetic_nord_tree(Path(tmp))
            first = read_dt_pinctrl(str(root), "nord-iq10")
            second = read_dt_pinctrl(str(root), "nord-iq10")

            first_bytes = json.dumps(first, sort_keys=True).encode("utf-8")
            second_bytes = json.dumps(second, sort_keys=True).encode("utf-8")

            if first_bytes != second_bytes:
                raise AssertionError(
                    "T-SRC-A2-4: two invocations of read_dt_pinctrl on the "
                    "same kernel tree produced diverging canonical-JSON "
                    "bytes. The reader must be deterministic — sorted "
                    "iteration over dir listings, stable insertion order "
                    "into output dicts, no time / uuid / hash injection.\n"
                    f"  first : {first_bytes!r}\n"
                    f"  second: {second_bytes!r}"
                )


if __name__ == "__main__":
    unittest.main()
