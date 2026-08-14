from lib.image_spec import (CAROUSEL, MIN_PDF_CROP_WIDTH, MIN_TRIP_CROP_WIDTH,
                            SECTION, THUMBNAIL, TRIP, crop_window)


def test_crop_window_is_bounded_by_the_short_edge():
    # The case that made a 1.65 upscale ceiling reject every brochure photo:
    # a 942x579 file looks big until you ask for 4:3 out of it.
    assert crop_window(942, 579, 4 / 3) == (772, 579)


def test_crop_window_of_a_portrait_is_bounded_by_width():
    assert crop_window(1024, 1166, 4 / 3) == (1024, 768)


def test_crop_window_leaves_an_exact_ratio_alone():
    assert crop_window(1440, 1080, 4 / 3) == (1440, 1080)


def test_carousel_and_section_share_one_ratio():
    # Uniform ratio across slots is the whole point of the house standard.
    assert CAROUSEL.aspect == SECTION.aspect == THUMBNAIL.aspect == 4 / 3


def test_carousel_floor_admits_the_launch_brochures():
    # Measured 4:3 crop widths across the three launch decks run 719-860px.
    # The floor has to sit under that or PDF-first delivers nothing.
    assert CAROUSEL.min_source_width == 720
    assert SECTION.min_source_width < CAROUSEL.min_source_width


def test_every_slot_stays_under_the_skybear_6mb_cap():
    for slot in (CAROUSEL, SECTION, THUMBNAIL):
        assert slot.max_bytes < 6 * 1024 * 1024


# --- the trip slot, and why it has its own floor -----------------------------
# Measured on tours/112 (2026-08-14, viewport 1291×707): the per-day section
# image renders at 220×165 and the trip tile at 89×89, but the tiles are
# cursor:zoom-in and open a lightbox that renders 535×643 off a 1080×1297
# source. The lightbox is the floor, not the tile. See docs/DESIGN.md 3.6.1.

def test_trip_targets_the_house_1080_long_edge():
    # Same bar the live catalogue already ships (lib/catalogue_source.py),
    # so this is not a new standard, and it clears the ~750px lightbox on a
    # tall viewport with room to spare.
    assert max(TRIP.width, TRIP.height) == 1080
    assert TRIP.width / TRIP.height == SECTION.width / SECTION.height


def test_trip_floor_is_lower_than_section_floor():
    # The whole point of the slot. A brochure photo cropping to 492px cannot
    # serve a 1200px section tile but is fine behind a 535px lightbox.
    assert MIN_TRIP_CROP_WIDTH < MIN_PDF_CROP_WIDTH


def test_the_five_recoverable_brochure_crops_clear_trip_but_not_section():
    # The actual measured crop widths of the seven real photographs the
    # section-derived floor was discarding. Five come back; 446 and 420 stay
    # out, and staying out is the correct answer for them — at TRIP's 1080
    # target they would be upscaled past the 2.2 ceiling.
    recoverable = [610, 590, 513, 492, 492]
    still_too_small = [446, 420]
    for crop in recoverable:
        assert crop < MIN_PDF_CROP_WIDTH
        assert crop >= MIN_TRIP_CROP_WIDTH
    for crop in still_too_small:
        assert crop < MIN_TRIP_CROP_WIDTH


def test_lowering_the_section_floor_is_not_the_fix():
    # Guards the reasoning, not just the number: SECTION is the only per-day
    # image that ever renders large, so it keeps the stricter floor even
    # though it is the one that looked too strict.
    assert MIN_PDF_CROP_WIDTH == SECTION.min_source_width
    assert MIN_TRIP_CROP_WIDTH == TRIP.min_source_width
