
from shapely.geometry import box, mapping

from eudr.models import Assessment, Case, Lot, Plot, ScreenMetrics, Supplier, Verdict
from eudr.tools.legal.overlay import run_overlays
from eudr.tools.risk.score import score
from eudr.tools.volume.reconcile import reconcile


def _case():
    c = Case(operator="op", origin_country="BR")
    c.suppliers = [Supplier(id="s1", name="Santa Rita", tax_id="98.765.432/0001-10"), Supplier(id="s2", name="Três Irmãos", tax_id="55.666.777/0001-88")]
    c.plots = [Plot(id="pa", supplier_id="s1", name="Gleba B", geometry=mapping(box(-55.660, -12.600, -55.640, -12.580)), computed_area_ha=480),
               Plot(id="pb", supplier_id="s2", name="TI", geometry=mapping(box(-55.300, -13.300, -55.270, -13.280)), computed_area_ha=720)]
    c.lots = [Lot(id="l1", reference="L1", tonnes=1500, plot_ids=["pa"]), Lot(id="l2", reference="L2", tonnes=9000, plot_ids=["pb"]), Lot(id="l3", reference="L3", tonnes=800)]
    return c


def test_overlays_find_indigenous_land_and_embargo(layers_dir):
    f = run_overlays(_case(), layers_dir)
    layers = {(x.layer, x.subject_ref) for x in f}
    assert ("indigenous_land", "pa") in layers
    assert ("embargo_list", "s2") in layers
    assert any(x.layer == "cerrado_biome" and x.severity == "info" for x in f)


def test_volume_flags():
    v = {x.lot_id: x for x in reconcile(_case())}
    assert v["l1"].flag is False and abs(v["l1"].plausible_t - 1680) < 1
    assert v["l2"].flag is True and v["l2"].ratio > 3
    assert v["l3"].flag is True and "cannot be traced" in v["l3"].detail


def test_risk_score_levels():
    c = _case()
    c.assessments = [Assessment(subject_ref="pa", rule_pack_version="t", verdict=Verdict.PASS, confidence=0.9,
                                metrics=ScreenMetrics(plot_area_ha=480, forest_2020_ha=0, loss_after_cutoff_ha=0, converted_ha=0)),
                     Assessment(subject_ref="pb", rule_pack_version="t", verdict=Verdict.CRITICAL, confidence=0.9,
                                metrics=ScreenMetrics(plot_area_ha=720, forest_2020_ha=200, loss_after_cutoff_ha=40, converted_ha=40))]
    c.volume_checks = reconcile(c)
    r = score(c)
    assert r.country_risk == "standard" and r.criteria["red_plots"] == 1 and r.criteria["level"] in ("medium", "high")
    c.assessments[1].override_verdict = Verdict.PASS; c.volume_checks = []
    assert score(c).score < r.score
