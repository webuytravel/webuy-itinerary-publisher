import numpy as np
import pytest
from PIL import Image

from lib.image_plan import ImagePlan, Placement, materialise


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
