import pytest
from shapely.geometry import box, mapping

from eudr.models import Verdict
from eudr.tools.geo.providers.mock import SCENARIOS, MockProvider, _geom_key
from eudr.tools.geo.screen import screen

GEOM = mapping(box(-55.92, -13.12, -55.88, -13.09))
EXPECTED = {
    "green_established": Verdict.PASS, "green_forest_intact": Verdict.PASS, "green_small_loss": Verdict.PASS,
    "red_reserve_cleared": Verdict.CRITICAL, "red_partial_edge": Verdict.CRITICAL, "amber_fire_no_conversion": Verdict.EXCEPTION,
    "amber_discordant": Verdict.EXCEPTION, "cerrado_savanna": Verdict.PASS,
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_scenario_verdict(scenario):
    prov = MockProvider({_geom_key(GEOM): scenario})
    v, conf, reason, m, layers = screen(prov.rasters(GEOM))
    assert v == EXPECTED[scenario], reason
    assert 1300 < m.plot_area_ha < 1600
    if scenario == "cerrado_savanna":
        assert m.native_vegetation_loss_ha > 1000 and m.forest_2020_ha == 0
    if scenario.startswith("red"):
        assert m.converted_ha >= 0.5 and m.first_loss_year in (2022, 2023)
    if scenario == "amber_fire_no_conversion":
        assert m.converted_ha == 0 and m.loss_after_cutoff_ha > 100
    if scenario == "amber_discordant":
        assert m.sources_concordant is False


def test_small_patches_dropped():
    prov = MockProvider({_geom_key(GEOM): "green_small_loss"})
    _, _, _, m, _ = screen(prov.rasters(GEOM))
    assert m.loss_after_cutoff_ha < 0.5
