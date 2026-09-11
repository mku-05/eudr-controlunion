"""English-language twin of case_mt_2027: same plots and scenarios, English file names, headers and documents."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import box, mapping

from tests.fixtures.build_fixtures import PLOTS, SUPPLIERS, _lines

HERE = Path(__file__).parent
CASE = HERE / "case_en_2027"
NAMES = {
    "Fazenda Boa Vista - Talhão 1": "Boa Vista Farm - Field 1", "Fazenda Boa Vista - Talhão 2": "Boa Vista Farm - Field 2",
    "Fazenda Boa Vista - Talhão 3": "Boa Vista Farm - Field 3", "Fazenda Santa Rita - Gleba A": "Santa Rita Farm - Block A",
    "Fazenda Santa Rita - Gleba B": "Santa Rita Farm - Block B", "Sítio Recanto": "Recanto Smallholding",
    "Fazenda Três Irmãos": "Three Brothers Farm", "Fazenda Chapadão": "Chapadao Farm S/A",
}
SUP_EN = {"sup_boavista": "Boa Vista Farm Ltd", "sup_santarita": "Santa Rita Agro", "sup_recanto": "Recanto Smallholding",
          "sup_tresirmaos": "Three Brothers Farm", "sup_chapadao": "Chapadao Farm S/A", "sup_semdados": "No-Data Cooperative"}


def build() -> Path:
    CASE.mkdir(parents=True, exist_ok=True)
    feats = []
    for name, sup, x, y, w, h, sc in PLOTS:
        feats.append({"type": "Feature", "geometry": mapping(box(x, y, x + w, y + h)),
                      "properties": {"name": NAMES[name], "supplier": sup, "declared_area_ha": None, "scenario": sc,
                                     "planting": "2026-10-05", "harvest": "2027-02-20"}})
    feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-55.40, -13.00], [-55.38, -12.98], [-55.40, -12.98], [-55.38, -13.00], [-55.40, -13.00]]]},
                  "properties": {"name": "Three Brothers Farm - North Field", "supplier": "sup_tresirmaos", "scenario": "green_established", "planting": "2026-10-01", "harvest": "2027-02-15"}})
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [-55.45, -12.95]},
                  "properties": {"name": "Recanto Smallholding - Area 2", "supplier": "sup_recanto", "declared_area_ha": 120, "scenario": "green_established"}})
    (CASE / "plots.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, indent=1))
    with open(CASE / "suppliers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["key", "supplier", "car", "tax_id", "municipality", "state", "email"])
        for k, (_, car, cnpj, mun, uf, mail) in SUPPLIERS.items():
            w.writerow([k, SUP_EN[k], car or "", cnpj, mun, uf, mail or ""])
    with open(CASE / "lots.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["lot", "tonnes", "plots", "silo", "destination"])
        w.writerow(["LOT-2027-001", 4200, "Boa Vista Farm - Field 1;Boa Vista Farm - Field 2;Boa Vista Farm - Field 3", "Silo LRV-2", "Rotterdam"])
        w.writerow(["LOT-2027-002", 9000, "Santa Rita Farm - Block A;Santa Rita Farm - Block B", "Silo Sorriso-1", "Rotterdam"])
        w.writerow(["LOT-2027-003", 1500, "Recanto Smallholding;Three Brothers Farm", "Silo Nova Mutum", "Rotterdam"])
        w.writerow(["LOT-2027-004", 800, "No-Data Cooperative", "Silo Sinop", "Rotterdam"])
    (CASE / "brief.md").write_text(
        "Operator: Cerrado Grains Export Ltd\nCommodity: soybeans (HS 1201)\nOrigin: Brazil (MT, BA)\nDestination: Rotterdam, NL\n"
        "Shipment: February 2027\nTotal: 15,500 t\n\nNote: No-Data Cooperative has not yet sent plot polygons.\n")
    _lines(CASE / "contract_santarita.pdf", "SOYBEAN PURCHASE AGREEMENT", [
        "Seller: Santa Rita Agro, tax id 98.765.432/0001-10", "CAR: MT-5107925-1234ABCD5678EF9012345678901234AB",
        "Buyer: Cerrado Grains Export Ltd", "Quantity: 9,000 tonnes of soybeans, 2026/2027 season",
        "Origin: Santa Rita Farm, Sorriso - MT", "Production period: planting October 2026, harvest February 2027",
        "Declaration: the seller states that no deforestation occurred on the area after 2020."])
    _lines(CASE / "chain_of_custody_manifest.pdf", "CHAIN OF CUSTODY MANIFEST — SOYBEANS — 2026/2027 SEASON", [
        "Issuer: Cerrado Grains Export Ltd, tax id 33.444.555/0001-66", "Issue date: 2027-03-05      Model: physical segregation (EUDR)", "",
        "TIER 1 (producer) -> TIER 2 (warehouse)",
        "Boa Vista Farm Ltd (tax id 12.345.678/0001-90) -> Silo LRV-2: 4,300 t, weigh tickets 1181-1240, 2027-02-22 to 2027-03-01",
        "Santa Rita Agro (tax id 98.765.432/0001-10) -> Silo Sorriso-1: 9,000 t, weigh tickets 2001-2140, 2027-02-18 to 2027-03-02",
        "Recanto Smallholding (tax id 11.222.333/0001-44) -> Silo Nova Mutum: 600 t, weigh tickets 3001-3010",
        "Three Brothers Farm (tax id 55.666.777/0001-88) -> Silo Nova Mutum: 700 t, weigh tickets 3011-3022",
        "No-Data Cooperative (tax id 77.888.999/0001-22) -> Silo Sinop: 800 t, weigh tickets 4001-4012", "",
        "TIER 2 (warehouse) -> TIER 3 (exporter)",
        "Silo LRV-2 -> Cerrado Grains: 4,200 t, lot LOT-2027-001, CT-e 77812",
        "Silo Sorriso-1 -> Cerrado Grains: 9,000 t, lot LOT-2027-002, CT-e 77813",
        "Silo Nova Mutum -> Cerrado Grains: 1,500 t, lot LOT-2027-003, CT-e 77814",
        "Silo Sinop -> Cerrado Grains: 800 t, lot LOT-2027-004, CT-e 77815", "",
        "Declaration: the lots above were kept segregated from untraced soy."],
        ["Signed: logistics manager, 2027-03-05", "Note: Silo Nova Mutum received 1,300 t and dispatched 1,500 t in the period."])
    _lines(CASE / "traceability_certificate_boavista.pdf", "MULTI-TIER TRACEABILITY CERTIFICATE — No. TC-2027-0117", [
        "Holder: Boa Vista Farm Ltd, tax id 12.345.678/0001-90", "CAR: MT-5105259-ABCD1234EF5678901234567890ABCDEF",
        "Municipality: Lucas do Rio Verde - MT     Biome: Cerrado",
        "Total property area: 2,180 ha   Legal reserve: 436 ha   Cultivated: 1,640 ha",
        "Fields: Field 1 (1,020 ha), Field 2 (560 ha), Field 3 (60 ha)", "Reference coordinates: -13.110000, -55.905000",
        "Chain: Boa Vista Farm -> Silo LRV-2 -> Cerrado Grains Export -> Rotterdam (NL)",
        "Product: soybeans, HS 1201.90.00, 2026/2027 season, 4,200 t",
        "Producer declaration: no deforestation or conversion of native vegetation after 31/12/2020 on the listed fields.",
        "Field audit: 2026-11-14, auditor CU-MT-07 (on-site visit, GPS checked).", "Valid until: 2027-12-31"])
    from tests.fixtures.build_fixtures import _scanned_car
    _scanned_car(CASE / "car_receipt_threebrothers_scan.pdf")
    return CASE


if __name__ == "__main__":
    print(build())
