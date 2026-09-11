"""Deterministic mapping of parsed files → Case. Used without agents and as the fallback the Intake agent refines."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from eudr.models import Case, Gap, GapKind, Lot, Plot, Supplier
from eudr.tools.docs.extract import extract_text
from eudr.tools.geo.parse import parse_file

GEO_EXT = (".geojson", ".json", ".shp", ".kml", ".kmz", ".zip", ".gpkg")
TAB_EXT = (".csv", ".xlsx")
DOC_EXT = (".pdf", ".txt", ".md")


def _pick(row: dict, *names, default=None):
    low = {k.lower(): v for k, v in row.items()}
    for n in names:
        if n in low and low[n] not in (None, ""):
            return low[n]
    return default


def _date(v) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(v))
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def _num(v) -> float | None:
    if isinstance(v, str):
        t = v.strip().replace(" ", "")
        if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):      # 1.300,5 (pt/es)
            t = t.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", t):    # 1,300.5 (en)
            t = t.replace(",", "")
        else:
            t = t.replace(",", ".")
        v = t
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_folder(folder: Path) -> tuple[str, list[dict], dict[str, list[dict]], dict[str, str]]:
    brief, features, tables, docs = "", [], {}, {}
    for f in sorted(folder.iterdir()):
        ext = f.suffix.lower()
        if f.name.lower().startswith("brief"):
            brief = f.read_text()
        elif ext in GEO_EXT:
            try:
                feats = parse_file(f)
            except Exception:
                continue
            for x in feats:
                x["_file"] = f.name
            features.extend(feats)
        elif ext in TAB_EXT:
            tables[f.name] = parse_file(f)
        elif ext in DOC_EXT:
            docs[f.name] = extract_text(f)
    return brief, features, tables, docs


def map_deterministic(operator: str | None, brief: str, features: list[dict], tables: dict[str, list[dict]]) -> Case:
    case = Case(operator=operator or _brief_field(brief, "operador", "operator") or "Unknown operator")
    case.destination = _brief_field(brief, "destino", "destination")
    case.shipment_window = _brief_field(brief, "embarque", "shipment")
    sup_by_key: dict[str, Supplier] = {}
    for name, rows in tables.items():
        for r in rows:
            if _pick(r, "razao_social", "razão social", "supplier", "fornecedor", "name", "nome") and not _pick(r, "toneladas", "tonnes"):
                key = str(_pick(r, "key", "chave", "id", default=_pick(r, "razao_social", "supplier", "fornecedor", "name", "nome")))
                s = Supplier(name=str(_pick(r, "razao_social", "razão social", "supplier", "fornecedor", "name", "nome")),
                             car_number=_pick(r, "car", "car_number"), tax_id=_pick(r, "cnpj", "cpf", "tax_id", "cuit"),
                             contact=_pick(r, "email", "contact", "telefone", "phone"), municipality=_pick(r, "municipio", "município", "municipality"),
                             state=_pick(r, "uf", "state", "estado"), country=str(_pick(r, "pais", "país", "country", default="BR"))[:2].upper())
                sup_by_key[key] = s
    case.suppliers = list(sup_by_key.values())
    name_to_plot: dict[str, Plot] = {}
    for i, f in enumerate(features):
        key = str(_pick(f, "supplier_key", "fornecedor", "supplier", "produtor", default="")).strip()
        s = sup_by_key.get(key)
        if s is None:
            s = Supplier(name=key or f"Unknown supplier {i}")
            sup_by_key[key or s.id] = s; case.suppliers.append(s)
        p = Plot(supplier_id=s.id, name=_pick(f, "nome", "name", "talhao", "talhão", "plot", default=f"feature-{i}"), geometry=f.get("geometry"),
                 geometry_source=f"upload:{f.get('_file', '?')}", declared_area_ha=_num(_pick(f, "area_declarada_ha", "area_ha", "area", "declared_area_ha")),
                 production_start=_date(_pick(f, "plantio", "production_start", "planting")), production_end=_date(_pick(f, "colheita", "production_end", "harvest")),
                 declared_yield_t_ha=_num(_pick(f, "produtividade", "yield_t_ha")), scenario=_pick(f, "scenario"))
        case.plots.append(p); name_to_plot[p.name] = p
    for name, rows in tables.items():
        for r in rows:
            t = _num(_pick(r, "toneladas", "tonnes", "tons", "quantidade"))
            if t is None:
                continue
            lot = Lot(reference=str(_pick(r, "lote", "lot", "reference", default=f"LOT-{len(case.lots) + 1}")), tonnes=t,
                      silo=_pick(r, "silo"), destination=_pick(r, "destino", "destination"))
            for nm in re.split(r"[;|]", str(_pick(r, "talhoes", "talhões", "plots", "plot_names", default=""))):
                nm = nm.strip()
                if not nm:
                    continue
                if nm in name_to_plot:
                    lot.plot_ids.append(name_to_plot[nm].id)
                else:
                    s = next((s for s in case.suppliers if s.name == nm), None)
                    if s:
                        case.gaps.append(Gap(kind=GapKind.MISSING_POLYGON, subject_ref=s.id, owner="supplier",
                                             description=f"Lot {lot.reference} names supplier '{nm}' but no plot polygons were provided."))
                    else:
                        case.gaps.append(Gap(kind=GapKind.OTHER, subject_ref=lot.id, owner="operator",
                                             description=f"Lot {lot.reference} references unknown plot/supplier '{nm}'."))
            case.lots.append(lot)
    return case


def _brief_field(brief: str, *keys) -> str | None:
    for k in keys:
        m = re.search(rf"(?im)^\s*{k}\s*:\s*(.+)$", brief or "")
        if m:
            return m[1].strip()
    return None


def apply_delta(case: Case, delta, features: list[dict]) -> Case:
    """Rebuild suppliers/plots/lots from the Intake agent's delta, keeping geometries from parsed features."""
    case.operator = delta.operator or case.operator
    case.commodity, case.origin_country = delta.commodity, delta.origin_country
    case.destination, case.shipment_window, case.intake_notes = delta.destination, delta.shipment_window, delta.notes
    sup: dict[str, Supplier] = {}
    for s in delta.suppliers:
        sup[s.key] = Supplier(name=s.name, country=s.country, car_number=s.car_number, tax_id=s.tax_id, contact=s.contact,
                              municipality=s.municipality, state=s.state)
    case.suppliers = list(sup.values())
    case.plots, name_to_plot = [], {}
    for p in delta.plots:
        s = sup.get(p.supplier_key) or next(iter(sup.values()), None)
        if s is None:
            s = Supplier(name=p.supplier_key); sup[p.supplier_key] = s; case.suppliers.append(s)
        geom = features[p.feature_index].get("geometry") if p.feature_index is not None and p.feature_index < len(features) else None
        pl = Plot(supplier_id=s.id, name=p.name, geometry=geom, geometry_source=f"upload:{features[p.feature_index].get('_file')}" if geom else None,
                  declared_area_ha=p.declared_area_ha, production_start=p.production_start, production_end=p.production_end,
                  declared_yield_t_ha=p.declared_yield_t_ha, scenario=(features[p.feature_index].get("scenario") if p.feature_index is not None and p.feature_index < len(features) else None))
        case.plots.append(pl); name_to_plot[pl.name] = pl
    case.lots = []
    for l in delta.lots:
        lot = Lot(reference=l.reference, tonnes=l.tonnes, silo=l.silo, destination=l.destination,
                  plot_ids=[name_to_plot[n].id for n in l.plot_names if n in name_to_plot])
        case.lots.append(lot)
        for k in l.supplier_keys_without_plots:
            if k in sup:
                case.gaps.append(Gap(kind=GapKind.MISSING_POLYGON, subject_ref=sup[k].id, owner="supplier",
                                     description=f"Lot {lot.reference}: supplier {sup[k].name} has no plot polygons."))
    for g in delta.gaps:
        kind = GapKind(g.kind) if g.kind in GapKind.__members__.values() else GapKind.OTHER
        ref = next((s.id for k, s in sup.items() if k == g.subject or s.name == g.subject), None) or next((p.id for p in case.plots if p.name == g.subject), g.subject)
        case.gaps.append(Gap(kind=kind, subject_ref=ref, owner=g.owner, description=g.description))
    return case
