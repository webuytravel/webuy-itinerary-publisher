from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib.image_plan import (GAP_NO_ITEMS, GAP_NO_MATCH, GAP_NO_SUBJECT,
                            ImagePlan, Placement, assign_trip_photos,
                            materialise, section_gap)


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


# --- landmark cards reuse what the plan already holds ------------------------
# The live reference product renders three photos under every landmark card
# (tours/112 carries 68); all five products shipped that layer empty. About
# half of it closes with no new sourcing, because a day's section photo
# usually is a photo of one of that day's landmarks.

def _sections(*days):
    """days = ((day_no, [item_subject, ...]), ...)"""
    return [{"day": d, "trip_items": [{"title": {"en": s}, "photo_subject": s}
                                      for s in items]} for d, items in days]


def _exact(subject, label):
    return 1.0 if subject.lower() == label.lower() else 0.0


def test_a_card_gets_the_day_photo_that_depicts_it():
    plan = _plan(_section("/tmp/a.jpg", position=6, subject="Yungang Grottoes"))
    assign_trip_photos(plan, _sections((6, ["Yungang Grottoes"])), _exact, 0.5)
    trips = plan.of("trip")
    assert [(t.position, t.trip_index) for t in trips] == [(6, 0)]
    assert trips[0].src_path == "/tmp/a.jpg"


def test_a_card_nothing_depicts_is_left_empty_rather_than_filled():
    # An unrelated photo on a card is worse than an empty card: it is the
    # wrong-place failure (docs/DESIGN.md 6.7) with extra steps.
    plan = _plan(_section("/tmp/a.jpg", position=6, subject="Yungang Grottoes"))
    assign_trip_photos(plan, _sections((6, ["Hanging Temple"])), _exact, 0.5)
    assert plan.of("trip") == []


def test_one_photo_cannot_paper_over_a_whole_day():
    # Without the reuse cap the single good photo of a day lands on every
    # card and the page shows the same picture four times.
    plan = _plan(_section("/tmp/a.jpg", position=2, subject="Ordos Grassland"))
    sections = _sections((2, ["Ordos Grassland"] * 4))
    assign_trip_photos(plan, sections, _exact, 0.5, per_item=1, max_reuse=2)
    assert len(plan.of("trip")) == 2


def test_credit_and_licence_survive_onto_the_card():
    # Commons photos carry an author and a licence; a trip photo is another
    # public use of the same file, so it has to carry them too.
    source = _section("/tmp/a.jpg", position=3, subject="Western Xia Tombs")
    source.credit, source.license = "Thebrainchamber1", "CC BY-SA 4.0"
    plan = _plan(source)
    assign_trip_photos(plan, _sections((3, ["Western Xia Tombs"])), _exact, 0.5)
    trip = plan.of("trip")[0]
    assert (trip.credit, trip.license) == ("Thebrainchamber1", "CC BY-SA 4.0")


def test_trip_photos_get_their_own_filenames_per_card(tmp_path):
    # position alone stops being unique once a day has several cards.
    plan = _plan(_section(_photo(tmp_path / "a.png"), position=4, subject="X"),
                 _section(_photo(tmp_path / "b.png"), position=4, subject="Y"))
    assign_trip_photos(plan, _sections((4, ["X", "Y"])), _exact, 0.5)
    materialise(plan, tmp_path / "out")
    names = sorted(Path(p.out_path).name for p in plan.of("trip"))
    assert names == ["trip_04_00_0.jpg", "trip_04_01_0.jpg"]
