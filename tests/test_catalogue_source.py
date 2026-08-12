import json

from lib.catalogue_source import CatalogueImage, match, parse_harvest


def test_parse_drops_the_product_hero():
    # The first image on a product page is the product's own hero and its
    # alt is the tour title, which matches no day.
    raw = json.dumps([
        ["RJZ3H6T5", "10D8N Desert And Grassland Dual Experience Hohhot"],
        ["Liw49dkw", "Maling River Canyon"],
    ])
    images = parse_harvest(raw, "tours/75-10d8n-desert-and-grassland")
    assert [i.image_id for i in images] == ["Liw49dkw"]


def test_parse_accepts_a_list_as_well_as_json():
    images = parse_harvest([["abc", "Kanas Lake"]], "tours/112-altay")
    assert images[0].alt == "Kanas Lake"


def test_parse_skips_blank_alts():
    images = parse_harvest([["abc", "  "], ["def", "Hemu Village"]], "tours/112-x")
    assert [i.image_id for i in images] == ["def"]


def test_url_points_at_the_oss_bucket():
    image = CatalogueImage(image_id="Liw49dkw", alt="Maling River Canyon", tour="t")
    assert image.url == "https://prod-webuysg.oss.webuy.ren/travel-video/Liw49dkw.jpg"


def test_match_is_substring_not_exact():
    # Live alt text carries trailing inclusions, so exact matching would
    # miss almost every entry.
    images = [
        CatalogueImage("a", "Wanfenglin (Ten Thousand Peaks Forest) (includes eco-cart)", "t"),
        CatalogueImage("b", "Jiaxiu Pavilion", "t"),
    ]
    assert [i.image_id for i in match(images, ["wanfenglin"])] == ["a"]


def test_match_takes_any_of_several_terms():
    images = [
        CatalogueImage("a", "Urho Ghost City (Devil's Town)", "t"),
        CatalogueImage("b", "Duku Highway", "t"),
        CatalogueImage("c", "Kazanqi Folk Street", "t"),
    ]
    got = {i.image_id for i in match(images, ["ghost city", "duku"])}
    assert got == {"a", "b"}
