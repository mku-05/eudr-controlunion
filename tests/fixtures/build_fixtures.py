"""Builds the synthetic client folder used by tests and demos: plots, suppliers, lots, docs, legal layers."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import box, mapping

HERE = Path(__file__).parent
CASE = HERE / "case_mt_2027"
LAYERS = HERE / "layers"

# Mato Grosso, around Lucas do Rio Verde / Sorriso. Each plot ~1.5–3 km boxes.
PLOTS = [
    ("Fazenda Boa Vista - Talhão 1", "sup_boavista", -55.920, -13.120, 0.030, 0.020, "green_established"),
    ("Fazenda Boa Vista - Talhão 2", "sup_boavista", -55.880, -13.120, 0.025, 0.020, "green_forest_intact"),
    ("Fazenda Santa Rita - Gleba A", "sup_santarita", -55.700, -12.600, 0.030, 0.025, "red_reserve_cleared"),
    ("Fazenda Santa Rita - Gleba B", "sup_santarita", -55.660, -12.600, 0.020, 0.020, "red_partial_edge"),
    ("Sítio Recanto", "sup_recanto", -55.500, -12.900, 0.020, 0.015, "amber_fire_no_conversion"),
    ("Fazenda Três Irmãos", "sup_tresirmaos", -55.300, -13.300, 0.030, 0.020, "amber_discordant"),
    ("Fazenda Chapadão", "sup_chapadao", -46.200, -12.100, 0.030, 0.030, "cerrado_savanna"),
    ("Fazenda Boa Vista - Talhão 3", "sup_boavista", -55.850, -13.120, 0.010, 0.010, "green_small_loss"),
]
SUPPLIERS = {
    "sup_boavista": ("Fazenda Boa Vista Ltda", "MT-5105259-ABCD1234EF5678901234567890ABCDEF", "12.345.678/0001-90", "Lucas do Rio Verde", "MT", "joao@boavista.example"),
    "sup_santarita": ("Agropecuária Santa Rita", "MT-5107925-1234ABCD5678EF9012345678901234AB", "98.765.432/0001-10", "Sorriso", "MT", "maria@santarita.example"),
    "sup_recanto": ("Sítio Recanto", None, "11.222.333/0001-44", "Nova Mutum", "MT", "recanto@example"),
    "sup_tresirmaos": ("Fazenda Três Irmãos", "MT-5106224-AAAA1111BBBB2222CCCC3333DDDD4444", "55.666.777/0001-88", "Lucas do Rio Verde", "MT", None),
    "sup_chapadao": ("Fazenda Chapadão S/A", "BA-2903201-FFFF0000EEEE1111DDDD2222CCCC3333", "22.333.444/0001-55", "Barreiras", "BA", "chapadao@example"),
    "sup_semdados": ("Cooperativa Sem Dados", None, "77.888.999/0001-22", "Sinop", "MT", "coop@example"),
}


def build() -> Path:
    CASE.mkdir(parents=True, exist_ok=True); LAYERS.mkdir(parents=True, exist_ok=True)
    feats = []
    for name, sup, x, y, w, h, sc in PLOTS:
        g = box(x, y, x + w, y + h)
        feats.append({"type": "Feature", "geometry": mapping(g),
                      "properties": {"nome": name, "supplier_key": sup, "area_declarada_ha": None, "scenario": sc,
                                     "plantio": "2026-10-05", "colheita": "2027-02-20"}})
    # one self-intersecting bow-tie polygon and one point for a >4 ha plot
    feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-55.40, -13.00], [-55.38, -12.98], [-55.40, -12.98], [-55.38, -13.00], [-55.40, -13.00]]]},
                  "properties": {"nome": "Fazenda Três Irmãos - Talhão Norte", "supplier_key": "sup_tresirmaos", "scenario": "green_established", "plantio": "2026-10-01", "colheita": "2027-02-15"}})
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [-55.45, -12.95]},
                  "properties": {"nome": "Sítio Recanto - Área 2", "supplier_key": "sup_recanto", "area_declarada_ha": 120, "scenario": "green_established"}})
    (CASE / "talhoes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, indent=1))

    with open(CASE / "fornecedores.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["key", "razao_social", "car", "cnpj", "municipio", "uf", "email"])
        for k, (n, car, cnpj, mun, uf, mail) in SUPPLIERS.items():
            w.writerow([k, n, car or "", cnpj, mun, uf, mail or ""])
    with open(CASE / "lotes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["lote", "toneladas", "talhoes", "silo", "destino"])
        w.writerow(["LOTE-2027-001", 4200, "Fazenda Boa Vista - Talhão 1;Fazenda Boa Vista - Talhão 2;Fazenda Boa Vista - Talhão 3", "Silo LRV-2", "Rotterdam"])
        w.writerow(["LOTE-2027-002", 9000, "Fazenda Santa Rita - Gleba A;Fazenda Santa Rita - Gleba B", "Silo Sorriso-1", "Rotterdam"])
        w.writerow(["LOTE-2027-003", 1500, "Sítio Recanto;Fazenda Três Irmãos", "Silo Nova Mutum", "Rotterdam"])
        w.writerow(["LOTE-2027-004", 800, "Cooperativa Sem Dados", "Silo Sinop", "Rotterdam"])
    (CASE / "brief.md").write_text(
        "Operador: Grãos do Cerrado Exportação Ltda\nCommodity: soja em grão (HS 1201)\nOrigem: Brasil (MT, BA)\n"
        "Destino: Rotterdam, NL\nEmbarque: fevereiro 2027\nTotal: 15.500 t\n\nObservação: Cooperativa Sem Dados ainda não enviou polígonos.\n")
    _pdf(CASE / "contrato_santarita.pdf")
    _coc_manifest(CASE / "manifesto_cadeia_custodia.pdf")
    _trace_cert(CASE / "certificado_rastreabilidade_boavista.pdf")
    _scanned_car(CASE / "car_recibo_tresirmaos_scan.pdf")

    # legal layers: an indigenous land touching Gleba B, a conservation unit far away, biome polygons, an embargo list
    layer = lambda name, geoms: (LAYERS / f"{name}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": mapping(g), "properties": p} for g, p in geoms]}))
    layer("indigenous_land", [(box(-55.650, -12.600, -55.600, -12.560), {"name": "TI Exemplo"})])
    layer("conservation_unit", [(box(-56.5, -13.9, -56.3, -13.7), {"name": "Parque Exemplo"})])
    layer("amazon_biome", [(box(-62.0, -12.8, -54.0, -7.0), {"name": "Amazônia (fixture)"})])
    layer("cerrado_biome", [(box(-56.0, -18.0, -44.0, -8.0), {"name": "Cerrado (fixture)"})])
    with open(LAYERS / "embargo_list.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["car_number", "tax_id", "source", "reason"])
        w.writerow(["", "55.666.777/0001-88", "IBAMA", "desmatamento sem autorização 2022"])
    return CASE


def _pdf(path: Path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in ["CONTRATO DE COMPRA E VENDA DE SOJA", "Vendedor: Agropecuária Santa Rita, CNPJ 98.765.432/0001-10",
                 "CAR: MT-5107925-1234ABCD5678EF9012345678901234AB", "Comprador: Grãos do Cerrado Exportação Ltda",
                 "Quantidade: 9.000 toneladas de soja em grão, safra 2026/2027", "Origem: Fazenda Santa Rita, Sorriso - MT",
                 "Período de produção: plantio outubro 2026, colheita fevereiro 2027", "Declaração: o vendedor afirma que a área não sofreu desmatamento após 2020."]:
        c.drawString(60, y, line); y -= 22
    c.save()


def _lines(path: Path, title: str, lines: list[str], page2: list[str] | None = None):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    def page(ls, t):
        y = 800; c.setFont("Helvetica-Bold", 13); c.drawString(60, y, t); y -= 30; c.setFont("Helvetica", 10)
        for line in ls:
            c.drawString(60, y, line); y -= 18
    page(lines, title)
    if page2:
        c.showPage(); page(page2, title + " (cont.)")
    c.save()


def _coc_manifest(path: Path):
    _lines(path, "MANIFESTO DE CADEIA DE CUSTÓDIA — SOJA EM GRÃO — SAFRA 2026/2027", [
        "Emitente: Grãos do Cerrado Exportação Ltda, CNPJ 33.444.555/0001-66",
        "Data de emissão: 2027-03-05      Modelo: segregação física (EUDR)",
        "",
        "NÍVEL 1 (produtor) -> NÍVEL 2 (armazém)",
        "Fazenda Boa Vista Ltda (CNPJ 12.345.678/0001-90) -> Silo LRV-2: 4.300 t, romaneios 1181-1240, 2027-02-22 a 2027-03-01",
        "Agropecuária Santa Rita (CNPJ 98.765.432/0001-10) -> Silo Sorriso-1: 9.000 t, romaneios 2001-2140, 2027-02-18 a 2027-03-02",
        "Sítio Recanto (CNPJ 11.222.333/0001-44) -> Silo Nova Mutum: 600 t, romaneios 3001-3010",
        "Fazenda Três Irmãos (CNPJ 55.666.777/0001-88) -> Silo Nova Mutum: 700 t, romaneios 3011-3022",
        "Cooperativa Sem Dados (CNPJ 77.888.999/0001-22) -> Silo Sinop: 800 t, romaneios 4001-4012",
        "",
        "NÍVEL 2 (armazém) -> NÍVEL 3 (exportador)",
        "Silo LRV-2 -> Grãos do Cerrado: 4.200 t, lote LOTE-2027-001, CT-e 77812",
        "Silo Sorriso-1 -> Grãos do Cerrado: 9.000 t, lote LOTE-2027-002, CT-e 77813",
        "Silo Nova Mutum -> Grãos do Cerrado: 1.500 t, lote LOTE-2027-003, CT-e 77814",
        "Silo Sinop -> Grãos do Cerrado: 800 t, lote LOTE-2027-004, CT-e 77815",
        "",
        "Declaração: os lotes acima foram mantidos segregados de soja não rastreada.",
    ], ["Assinatura: responsável logístico, 2027-03-05", "Observação: Silo Nova Mutum recebeu 1.300 t e expediu 1.500 t no período."])


def _trace_cert(path: Path):
    _lines(path, "CERTIFICADO DE RASTREABILIDADE MULTINÍVEL — Nº CR-2027-0117", [
        "Titular: Fazenda Boa Vista Ltda, CNPJ 12.345.678/0001-90",
        "CAR: MT-5105259-ABCD1234EF5678901234567890ABCDEF",
        "Município: Lucas do Rio Verde - MT     Bioma: Cerrado",
        "Área total do imóvel: 2.180 ha   Área de reserva legal: 436 ha   Área cultivada: 1.640 ha",
        "Talhões: Talhão 1 (1.020 ha), Talhão 2 (560 ha), Talhão 3 (60 ha)",
        "Coordenadas de referência: -13.110000, -55.905000",
        "Cadeia: Fazenda Boa Vista -> Silo LRV-2 -> Grãos do Cerrado Exportação -> Rotterdam (NL)",
        "Produto: soja em grão, NCM 1201.90.00, safra 2026/2027, 4.200 t",
        "Declaração do produtor: não houve desmatamento ou conversão de vegetação nativa após 31/12/2020 nos talhões listados.",
        "Auditoria de campo: 2026-11-14, auditor CU-MT-07 (visita presencial, GPS conferido).",
        "Validade: 2027-12-31",
    ])


def _scanned_car(path: Path):
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new("RGB", (1240, 1754), (246, 243, 236))
    dr = ImageDraw.Draw(img)
    lines = ["RECIBO DE INSCRICAO DO IMOVEL RURAL NO CAR", "Cadastro Ambiental Rural - SICAR", "",
             "Registro no CAR: MT-5106224-AAAA1111BBBB2222CCCC3333DDDD4444", "Imovel: Fazenda Tres Irmaos",
             "Municipio: Lucas do Rio Verde / MT", "Proprietario: Fazenda Tres Irmaos Ltda  CNPJ 55.666.777/0001-88",
             "Area do imovel: 1.480,00 ha   Reserva legal: 296,00 ha   APP: 41,20 ha",
             "Data de inscricao: 12/04/2017   Situacao: Ativo   Condicao: Aguardando analise", "",
             "Coordenadas do ponto central: -13.290000, -55.285000",
             "Observacao: area consolidada declarada 1.120 ha; area de vegetacao nativa remanescente 318 ha."]
    y = 140
    for ln in lines:
        dr.text((110, y), ln, fill=(40, 40, 40), font_size=30); y += 62
    img = img.rotate(0.6, fillcolor=(246, 243, 236)).filter(ImageFilter.GaussianBlur(0.7))
    img.save(path, "PDF", resolution=150)


if __name__ == "__main__":
    print(build())
