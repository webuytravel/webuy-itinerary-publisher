from lib.image_spec import CAROUSEL, SECTION, THUMBNAIL, crop_window


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
