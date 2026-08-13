import numpy as np
import pytest
from PIL import Image

from lib.image_plan import (GAP_NO_ITEMS, GAP_NO_MATCH, GAP_NO_SUBJECT,
                            ImagePlan, Placement, materialise, section_gap)


def _photo(path, width=2400, height=1600, seed=0):
    rng = np.random.default_rng(seed)
    Image.fromarray(
        rng.integers(0, 255, (height, width, 3), dtype=np.uint8), "RGB").save(path)
    return path


def _plan(*placements):
    return ImagePlan(type_code="WBTEST", region="CHN", placements=list(placements))


def _section(src_path, position=3, subject="Test Landmark"):
    return Placement(slot="section", position=position, origin="web",
                     subject=subject, source_ref="ref", src_path=str(src_path))


def test_a_present_source_is_normalised(tmp_path):
    plan = _plan(_section(_photo(tmp_path / "in.png")))
    materialise(plan, tmp_path / "out")
    placement = plan.placements[0]
    assert placement.out_path
    assert placement.bytes > 0


def test_a_missing_source_file_aborts_instead_of_noting_it(tmp_path):
    # This is the WBCURC day-3 failure. The override pointed at a file that
    # had been cleaned up; materialise used to append "source file missing"
    # to the note and carry on, so compose exited 0 with its usual summary
    # and the day silently shipped with no photo.
    plan = _plan(_section(tmp_path / "gone.jpg"))
    with pytest.raises(FileNotFoundError) as excinfo:
        materialise(plan, tmp_path / "out")
    assert "gone.jpg" in str(excinfo.value)


def test_a_placement_with_no_path_aborts(tmp_path):
    # Catalogue placements are created with an empty src_path and filled in
    # by a later resolution pass. One that arrives here still empty means
    # that pass missed it — a wiring bug, not a data condition.
    plan = _plan(Placement(slot="section", position=4, origin="catalogue",
                           subject="Unresolved", source_ref="tours/118"))
    with pytest.raises(FileNotFoundError) as excinfo:
        materialise(plan, tmp_path / "out")
    assert "no source path was ever resolved" in str(excinfo.value)


def test_every_missing_source_is_named_not_just_the_first(tmp_path):
    # One run should tell you the whole list to fix. WBCURC had ten.
    plan = _plan(_section(tmp_path / "a.jpg", position=1, subject="A"),
                 _section(tmp_path / "b.jpg", position=2, subject="B"),
                 _section(tmp_path / "c.jpg", position=3, subject="C"))
    with pytest.raises(FileNotFoundError) as excinfo:
        materialise(plan, tmp_path / "out")
    message = str(excinfo.value)
    assert "3 placement(s)" in message
    assert all(name in message for name in ("a.jpg", "b.jpg", "c.jpg"))


def test_nothing_is_written_when_one_source_is_missing(tmp_path):
    # The check runs before any encoding, so a failed run leaves no partial
    # out/ directory for a later step to mistake for a complete one.
    out = tmp_path / "out"
    plan = _plan(_section(_photo(tmp_path / "ok.png"), position=1),
                 _section(tmp_path / "gone.jpg", position=2))
    with pytest.raises(FileNotFoundError):
        materialise(plan, out)
    assert not out.exists()


# --- every dayless day must be reported ------------------------------------
# WBCHET D1 shipped to production 410 with no section photo and no mention of
# it anywhere: not on the review page, not in plan.json's gaps, not in
# compose's summary line. The day had two trip items ("Depart for Ordos via
# Kuala Lumpur", "Arrival and Hotel Check-In") and neither carried a
# photo_subject, so `if placed == 0 and subjects:` skipped the gap entirely.
# See docs/DESIGN.md 6.11.

def test_a_day_whose_items_carry_no_subject_still_reports_a_gap():
    gap = section_gap(1, has_items=True, subjects=[], fallback=["Ordos"])
    assert gap.reason == GAP_NO_SUBJECT
    # The city is the only thing left to search on — it has to survive into
    # the gap or the review page has nothing to show the person signing off.
    assert gap.subjects == ["Ordos"]


def test_a_day_with_subjects_that_matched_nothing_is_a_different_gap():
    gap = section_gap(2, has_items=True,
                      subjects=["Ningxia Museum"], fallback=["Yinchuan"])
    assert gap.reason == GAP_NO_MATCH
    assert gap.subjects == ["Ningxia Museum"]


def test_a_day_with_no_trip_items_is_still_a_gap_just_a_benign_one():
    # Pure return day. tours/112 leaves its last day blank too, so this one
    # is allowed to stay empty — but it is logged, not swallowed, because
    # "normal" is the reviewer's call and not compose's.
    gap = section_gap(9, has_items=False, subjects=[], fallback=["Singapore"])
    assert gap.reason == GAP_NO_ITEMS


def test_the_three_reasons_are_distinct():
    # The review page branches on them; collapsing any two would put an
    # unfilled day back under the benign "纯中转/抵离日" line.
    assert len({GAP_NO_MATCH, GAP_NO_SUBJECT, GAP_NO_ITEMS}) == 3
