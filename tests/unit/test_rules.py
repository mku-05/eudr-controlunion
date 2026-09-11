from eudr.models import ScreenMetrics, Verdict
from eudr.rules import decide_verdict


def m(**kw):
    base = dict(plot_area_ha=100, forest_2020_ha=0, loss_after_cutoff_ha=0, converted_ha=0, sources_concordant=True)
    base.update(kw)
    return ScreenMetrics(**base)


def test_no_forest_is_green():
    assert decide_verdict(m())[0] == Verdict.PASS


def test_forest_intact_is_green():
    assert decide_verdict(m(forest_2020_ha=40))[0] == Verdict.PASS


def test_loss_below_half_ha_is_green():
    assert decide_verdict(m(forest_2020_ha=40, loss_after_cutoff_ha=0.4, converted_ha=0.4))[0] == Verdict.PASS


def test_converted_concordant_is_red():
    v, conf, _ = decide_verdict(m(forest_2020_ha=40, loss_after_cutoff_ha=5, converted_ha=5, first_loss_year=2023))
    assert v == Verdict.CRITICAL and conf >= 0.9


def test_converted_discordant_is_amber():
    assert decide_verdict(m(forest_2020_ha=40, loss_after_cutoff_ha=5, converted_ha=5, sources_concordant=False))[0] == Verdict.EXCEPTION


def test_loss_without_conversion_is_amber():
    assert decide_verdict(m(forest_2020_ha=40, loss_after_cutoff_ha=5, converted_ha=0))[0] == Verdict.EXCEPTION
