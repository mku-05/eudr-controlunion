from datetime import date

from eudr.models import Case, GapKind, Plot, Supplier
from eudr.tools.geo.parse import parse_file
from eudr.tools.geo.validate import geodesic_area_ha, validate_case_plots, validate_plot

SQ = {"type": "Polygon", "coordinates": [[[-55.92, -13.12], [-55.88, -13.12], [-55.88, -13.09], [-55.92, -13.09], [-55.92, -13.12]]]}


def test_geodesic_area():
    assert 1400 < geodesic_area_ha(SQ) < 1500


def test_bowtie_repaired():
    bow = {"type": "Polygon", "coordinates": [[[-55.40, -13.00], [-55.38, -12.98], [-55.40, -12.98], [-55.38, -13.00], [-55.40, -13.00]]]}
    p, gaps = validate_plot(Plot(supplier_id="s", geometry=bow, production_start=date(2026, 10, 1), production_end=date(2027, 2, 1)), "BR")
    assert p.geometry["type"] in ("Polygon", "MultiPolygon") and p.computed_area_ha > 0
    assert any(g.kind == GapKind.INVALID_GEOMETRY and g.resolved for g in gaps)


def test_point_over_4ha_needs_polygon():
    p, gaps = validate_plot(Plot(supplier_id="s", geometry={"type": "Point", "coordinates": [-55.45, -12.95]}, declared_area_ha=120), "BR")
    assert any(g.kind == GapKind.POINT_TOO_LARGE for g in gaps)
    assert any(g.kind == GapKind.MISSING_PRODUCTION_WINDOW for g in gaps)


def test_swapped_latlon_flagged():
    swapped = {"type": "Polygon", "coordinates": [[[-13.12, -55.92], [-13.12, -55.88], [-13.09, -55.88], [-13.09, -55.92], [-13.12, -55.92]]]}
    _, gaps = validate_plot(Plot(supplier_id="s", geometry=swapped), "BR")
    assert any("outside BR" in g.description for g in gaps)


def test_duplicates_and_overlaps():
    c = Case(operator="op", suppliers=[Supplier(id="s", name="S")])
    c.plots = [Plot(id="a", supplier_id="s", geometry=SQ), Plot(id="b", supplier_id="s", geometry=SQ),
               Plot(id="c", supplier_id="s", geometry={"type": "Polygon", "coordinates": [[[-55.90, -13.12], [-55.86, -13.12], [-55.86, -13.09], [-55.90, -13.09], [-55.90, -13.12]]]})]
    gaps = validate_case_plots(c)
    kinds = [(g.kind, g.subject_ref) for g in gaps]
    assert (GapKind.OVERLAP, "b") in kinds and any(k == GapKind.OVERLAP and s == "c" for k, s in kinds)


def test_parse_fixture_files(fixture_case_dir):
    feats = parse_file(fixture_case_dir / "talhoes.geojson")
    assert len(feats) == 10 and feats[0]["geometry"]["type"] == "Polygon" and feats[0]["nome"]
    rows = parse_file(fixture_case_dir / "fornecedores.csv")
    assert len(rows) == 6 and rows[0]["razao_social"]
    lots = parse_file(fixture_case_dir / "lotes.csv")
    assert lots[0]["toneladas"] == "4200"
