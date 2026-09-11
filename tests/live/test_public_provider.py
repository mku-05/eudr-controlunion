from datetime import date

import pytest
from shapely.geometry import box, mapping

from eudr.tools.geo.providers.public import PublicProvider, hansen_tile, worldcover_tile
from eudr.tools.geo.screen import screen

pytestmark = pytest.mark.live


def test_tile_names():
    assert hansen_tile(-13.1, -55.9) == "10S_060W"
    assert hansen_tile(-10.0, -55.9) == "10S_060W"
    assert hansen_tile(5.0, -60.0) == "10N_060W"
    assert worldcover_tile(-13.1, -55.9) == "S15W057"
    assert worldcover_tile(-12.1, -46.2) == "S15W048"


def test_established_soya_field_is_green():
    g = mapping(box(-55.925, -13.125, -55.905, -13.110))  # Lucas do Rio Verde cropland
    v, conf, reason, m, _ = screen(PublicProvider().rasters(g))
    assert 250 < m.plot_area_ha < 400
    assert m.forest_2020_ha < 0.2 * m.plot_area_ha, m  # riparian strip exists; must be a minority
    assert v.value == "PASS" and m.loss_after_cutoff_ha < 0.5


def test_forest_area_has_baseline():
    g = mapping(box(-57.60, -9.70, -57.58, -9.68))  # Apiacás region, arc of deforestation
    v, conf, reason, m, _ = screen(PublicProvider().rasters(g))
    assert m.forest_2020_ha > 50, m
    print("verdict", v, reason, m)


def test_chip_and_ndvi():
    g = mapping(box(-55.925, -13.125, -55.905, -13.110))
    p = PublicProvider()
    chip = p.chip(g, date(2020, 8, 15))
    assert chip and chip.captured_at <= date(2020, 12, 31) and len(chip.png) > 10_000
    pts = p.ndvi_series(g, date(2024, 1, 1), date(2024, 12, 31), max_points=4)
    assert len(pts) >= 2 and all(-1 <= x.ndvi <= 1 for x in pts)
