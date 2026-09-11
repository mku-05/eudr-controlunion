"""Geometry and declaration checks that produce Gaps. Pure functions over the Case."""
from __future__ import annotations

from pyproj import Geod
from shapely.geometry import shape, mapping
from shapely.validation import make_valid

from eudr.models import Case, Gap, GapKind, Plot
from eudr.rules import RULE_PACK

_geod = Geod(ellps="WGS84")
COUNTRY_BBOX = {"BR": (-74.0, -34.0, -34.7, 5.3), "AR": (-73.6, -55.1, -53.6, -21.8), "PY": (-62.7, -27.6, -54.3, -19.3)}


def geodesic_area_ha(geometry: dict) -> float:
    g = shape(geometry)
    if g.geom_type == "Point":
        return 0.0
    area, _ = _geod.geometry_area_perimeter(g)
    return abs(area) / 10_000.0


def round_coords(geometry: dict, decimals: int = RULE_PACK.coordinate_decimals) -> dict:
    from shapely import set_precision
    g = set_precision(shape(geometry), 10 ** -decimals)
    return mapping(g)


def validate_plot(plot: Plot, country: str) -> tuple[Plot, list[Gap]]:
    gaps: list[Gap] = []
    if plot.geometry is None:
        gaps.append(Gap(kind=GapKind.MISSING_POLYGON, subject_ref=plot.id, owner="supplier",
                        description=f"Plot {plot.name or plot.id}: no geolocation. Polygon required if > 4 ha."))
        return plot, gaps
    g = shape(plot.geometry)
    if g.is_empty:
        gaps.append(Gap(kind=GapKind.INVALID_GEOMETRY, subject_ref=plot.id, description="Empty geometry."))
        return plot, gaps
    if not g.is_valid:
        fixed = make_valid(g)
        if fixed.geom_type in ("Polygon", "MultiPolygon") and fixed.area > 0:
            plot.geometry = mapping(fixed); g = fixed
            gaps.append(Gap(kind=GapKind.INVALID_GEOMETRY, subject_ref=plot.id, owner="analyst", resolved=True,
                            resolution="auto-repaired with make_valid",
                            description="Self-intersecting polygon repaired automatically; confirm boundary."))
        else:
            gaps.append(Gap(kind=GapKind.INVALID_GEOMETRY, subject_ref=plot.id, description="Geometry invalid and not repairable."))
            return plot, gaps
    plot.geometry = round_coords(plot.geometry)
    plot.computed_area_ha = round(geodesic_area_ha(plot.geometry), 2)

    if g.geom_type == "Point":
        if (plot.declared_area_ha or 0) > RULE_PACK.polygon_required_over_ha:
            gaps.append(Gap(kind=GapKind.POINT_TOO_LARGE, subject_ref=plot.id, owner="supplier",
                            description=f"Declared {plot.declared_area_ha} ha but only a point given; Art. 9(1)(d) requires a polygon > 4 ha."))
        elif plot.declared_area_ha is None:
            gaps.append(Gap(kind=GapKind.MISSING_POLYGON, subject_ref=plot.id, owner="supplier",
                            description="Point geometry with no declared area — cannot confirm the 4 ha polygon rule."))
    else:
        if plot.declared_area_ha and plot.computed_area_ha:
            ratio = plot.computed_area_ha / plot.declared_area_ha
            if ratio > 1.25 or ratio < 0.75:
                gaps.append(Gap(kind=GapKind.OTHER, subject_ref=plot.id, owner="supplier",
                                description=f"Polygon area {plot.computed_area_ha} ha vs declared {plot.declared_area_ha} ha (ratio {ratio:.2f})."))
    bbox = COUNTRY_BBOX.get(country)
    if bbox:
        cx, cy = g.centroid.x, g.centroid.y
        if not (bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]):
            gaps.append(Gap(kind=GapKind.INVALID_GEOMETRY, subject_ref=plot.id, owner="supplier",
                            description=f"Centroid ({cy:.4f}, {cx:.4f}) is outside {country}. Lat/lon swapped?"))
    if plot.production_start is None or plot.production_end is None:
        gaps.append(Gap(kind=GapKind.MISSING_PRODUCTION_WINDOW, subject_ref=plot.id, owner="supplier",
                        description="Production date range missing (required in the DDS)."))
    return plot, gaps


def validate_case_plots(case: Case) -> list[Gap]:
    gaps: list[Gap] = []
    for i, p in enumerate(case.plots):
        case.plots[i], g = validate_plot(p, case.origin_country)
        gaps.extend(g)
    # duplicates and overlaps
    shapes = [(p, shape(p.geometry)) for p in case.plots if p.geometry and shape(p.geometry).geom_type != "Point"]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            pi, gi = shapes[i]; pj, gj = shapes[j]
            if gi.equals(gj):
                gaps.append(Gap(kind=GapKind.OVERLAP, subject_ref=pj.id, owner="operator",
                                description=f"Plot {pj.name or pj.id} duplicates {pi.name or pi.id}."))
            elif gi.intersects(gj):
                inter = gi.intersection(gj).area / min(gi.area, gj.area)
                if inter > 0.01:
                    gaps.append(Gap(kind=GapKind.OVERLAP, subject_ref=pj.id, owner="operator",
                                    description=f"Plot {pj.name or pj.id} overlaps {pi.name or pi.id} by {inter:.0%} of the smaller plot."))
    return gaps
