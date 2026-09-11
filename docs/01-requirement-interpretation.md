# Control Union — EUDR Soya: Requirement Interpretation

_Status: interpretation of an informal brief. Nothing here has been confirmed with Control Union. Open questions are in §9._
_Date: 11 Sep 2026_

---

## 1. The brief as received

> "Control Union works with soya farming and needs to pass regulations like EUDR. They may provide a before and after image of land and we need to derive that no deforestation happened."

## 2. What is actually being asked for

Control Union (CU) is a **certification / inspection body**, not a farmer or trader. Its clients are the soya producers, crushers, and traders who must prove to the EU that their soya is EUDR-compliant. So the product is almost certainly:

> **An audit-grade platform that takes the geolocation of soya plots, independently verifies — using satellite data — that no forest on those plots was converted to agriculture after 31 Dec 2020, and produces defensible evidence that CU can put its name behind.**

The "before and after image" phrasing is the client's mental model of the *output* (a picture of the land in 2020 vs. now). It is not the *input*. The input is a **plot polygon**; the images are something the system generates, dates, and attaches as evidence. Client-supplied images cannot be primary evidence — their date, location and authenticity are unverifiable, and a regulator or CU's own accreditation body would not accept them.

## 3. The regulation, reduced to what constrains the product

Regulation (EU) 2023/1115 as amended Dec 2025; simplification package May/July 2026.

| Item | Rule | Product consequence |
|---|---|---|
| **Application date** | **30 Dec 2026** for large/medium operators; 30 Jun 2027 for micro/small. Confirmed firm — no further delay. | ~15 weeks from today. MVP must be usable for the first 2026/27 harvest shipments (Brazil harvest Jan–Apr 2027, so contracts are being fixed now). |
| **Cut-off date** | Product must be produced on land **not subject to deforestation after 31 Dec 2020**. | Every verdict = "forest baseline at 2020-12-31" vs "forest loss between 2021-01-01 and production date". The 2020 baseline is the single most important dataset. |
| **Forest definition** (Art. 2(4)) | Land > 0.5 ha, trees > 5 m, canopy cover > 10 % (or able to reach those in situ), **excluding land predominantly under agricultural or urban use**. | Not every tree loss is "deforestation". Cerrado savanna (huge for Brazilian soya) often does *not* meet 5 m / 10 %, while cerradão and gallery forest do. The engine must classify per the legal definition, not "vegetation loss". |
| **Deforestation** (Art. 2(3)) | Conversion of forest to **agricultural use**, whether human-induced or not. | Fire/windthrow with no conversion is not deforestation for soya (degradation only applies to wood). Post-loss land use must be classified (crop/pasture = conversion). |
| **Geolocation** (Art. 9(1)(d)) | Coordinates of **all plots** where the commodity was produced; **polygons for plots > 4 ha**; 6-decimal lat/long; plus production date/range. | Polygon ingest, validation, storage is core. Soya plots are almost all > 4 ha → polygons are the norm, not the exception. |
| **Plot-level, no mixing** | If any part of a plot was deforested after cut-off, product from that plot is non-compliant. | Partial overlaps kill the whole plot. Precision of polygon (field vs. whole fazenda) is a business decision the product must guide. |
| **Legality** (Art. 2(40)) | Produced in accordance with the relevant laws of the country of production: land tenure, environmental, labour, human rights, FPIC, tax, anti-corruption, trade. | Deforestation is necessary but not sufficient. A legality dossier per supplier is a second module. |
| **Risk assessment** (Art. 10) | Operators from **standard-risk** countries must do full risk assessment + mitigation. **Brazil and Argentina are standard risk** (list of 20 May 2025; review due 2026). Low-risk countries get simplified due diligence. | No shortcut for the main soya origins. A risk scoring module is needed. |
| **Who files a DDS** (post-amendment) | Only the operator first placing on the EU market (or exporting). Downstream operators/traders just reference upstream DDS numbers. Micro/small primary producers in *low-risk* countries may file a one-time simplified declaration with postal address. | Fewer DDS filers, but each one carries the full burden. Simplified declaration is irrelevant for Brazil/Argentina (standard risk). |
| **Information System** | DDS submitted to EU IS (TRACES); reopened June 2026 with updated API spec. | DDS export / API submission is a late-stage feature, not MVP. |
| **Records** | Keep due-diligence records 5 years; competent authorities can demand them. | Immutable audit trail, versioned evidence, retention. |
| **Penalties** | Fines ≥ 4 % of EU turnover, confiscation, market exclusion. | CU's clients need evidence that survives regulatory challenge — quality bar is "audit-grade", not "dashboard". |

## 4. Re-framing "before / after image" into the real technical problem

For each plot polygon, answer three questions with evidence:

1. **Was there forest (per EUDR definition) inside this polygon on 31 Dec 2020?**
   If no → plot is compliant on deforestation grounds (it was already cropland/pasture). Most Brazilian soya plots fall here. This is the cheap, high-volume path.
2. **If yes, was any of that forest lost between 1 Jan 2021 and the production date?**
   Use published loss/alert datasets *and* own change detection on the Sentinel time series.
3. **If lost, was it converted to agricultural use?**
   Post-loss land cover classification / visual check. Conversion → **non-compliant**.

Verdict per plot: **GREEN** (no 2020 forest, or no loss) · **AMBER** (loss detected, ambiguous — analyst review) · **RED** (confirmed conversion). Each carries: area affected (ha), confidence, datasets consulted, dated image chips, analyst notes, sign-off.

### Why a single "before / after" pair is not enough
- **Cloud**: Mato Grosso / Cerrado has months of cloud; a single clear optical pair may not exist near the dates you need. Sentinel-1 radar (cloud-penetrating) and multi-year time series solve this.
- **Seasonality**: soya harvest, pasture burn, dry season all look like "vegetation loss" in NDVI. A time series distinguishes a crop cycle from forest clearing.
- **Provenance**: the auditor must state which sensor, which date, which processing. Only platform-generated imagery has this.
- **Definition**: an image shows tree loss; the law asks about *forest per Art. 2(4)* converted to *agriculture*. That needs classified layers, not eyeballing.

### Data sources (all free unless noted)
| Purpose | Dataset |
|---|---|
| 2020 forest baseline | **JRC Global Forest Cover 2020** (EU's own reference map, 10 m); JRC Tropical Moist Forest; Hansen/UMD tree cover + lossyear; ESA WorldCover 2020/2021 (10 m) |
| Loss / alerts after 2020 | Hansen lossyear ≥ 2021; **GLAD-L / GLAD-S2** (Landsat / Sentinel-2); **RADD** (Sentinel-1 radar, works through cloud); **PRODES / DETER** (INPE — Brazil's official Amazon & Cerrado deforestation record; carries weight with auditors) |
| Imagery for evidence chips + own change detection | Sentinel-2 L2A (10 m, ~5-day), Sentinel-1 GRD, Landsat 8/9 (30 m); Planet NICFI basemaps (higher res, tropics; licence terms to check); commercial VHR (Planet/Maxar) for disputed plots only — paid |
| Legality / risk layers (Brazil) | **CAR/SICAR** property boundaries (the single best polygon source), IBAMA embargo list, Terras Indígenas (FUNAI), Unidades de Conservação, MTE "lista suja" (slave labour), Amazon Soy Moratorium (2008 cut-off — stricter than EUDR, Amazon biome only), biome boundaries (Amazon vs Cerrado), quilombola lands |
| Legality (Argentina / Paraguay) | Ley de Bosques OTBN zoning (red/yellow/green); Paraguay Zero Deforestation Law (Eastern region) |
| Global | WDPA protected areas, Global Forest Watch |
| Compute | Google Earth Engine or Copernicus Data Space / openEO — do not build a raster pipeline from scratch in 15 weeks |

## 5. Who uses it

| Persona | Needs |
|---|---|
| **CU auditor / GIS analyst** | Review queue of AMBER/RED plots, side-by-side dated imagery, NDVI/radar time series, draw/annotate, issue verdict, sign off, generate evidence pack, manage non-conformities & CAPA. Sampling tools for large supplier bases. |
| **CU client — operator/trader** (crusher, exporter, EU importer) | Upload supplier + plot data in bulk, see compliance status per plot/supplier/lot, volume reconciliation, export the data needed for their DDS (or push to TRACES). Standard-risk → risk assessment record. |
| **Supplier / farmer / cooperative** (Brazil, Argentina…) | Submit polygons (CAR shapefile upload, GeoJSON/KML, or mobile GPS walk), submit legality documents, see only their own status. Portuguese/Spanish. Low bandwidth. Confidentiality concerns (LGPD; farmers are reluctant to hand over polygons). |
| **CU management / scheme owner** | Portfolio dashboards, throughput, evidence retention, accreditation traceability. |
| **(Indirect) Competent authority** | Receives an evidence pack they can independently check. |

## 6. Functional scope

**Core (the product doesn't exist without these)**
1. **Plot & supplier ingest** — GeoJSON / Shapefile / KML / CSV / CAR; polygon validation (topology, self-intersections, area vs. declared, duplicates, overlaps across suppliers, inside declared country/municipality, ≥ 4 ha ⇒ polygon required); versioning.
2. **Deforestation screening engine** — automated GREEN / AMBER / RED per plot, per §4; batch and re-run on new alerts; per-plot area and confidence.
3. **Evidence generation** — dated before (≤ 2020-12-31) and after (near production date) image chips with source/cloud/date metadata; NDVI + radar time series chart; loss overlay; PDF/JSON evidence pack; content hash + timestamp.
4. **Analyst review workflow** — queue, assignment, verdict override with justification, second reviewer, sign-off, immutable audit log.
5. **Compliance status roll-up** — plot → supplier → lot/shipment → client; export of DDS-ready data (geolocation payload in EU IS GeoJSON format, production dates, quantities).

**Second wave**
6. **Risk assessment (Art. 10)** — structured scoring: country/sub-national risk, presence of forest, indigenous peoples, corruption, supply-chain complexity, prevalence of deforestation in the area, credible concerns (NGO reports), sanctions; mitigation actions; record.
7. **Legality dossier** — per-supplier checklist + documents (CAR status, land title, licences, labour), automated overlays with embargo / indigenous / protected-area layers.
8. **Volume reconciliation** — declared tonnes vs. plot area × regional yield; flags over-declaration (the classic way non-compliant soya gets laundered through compliant plots). This is what a certifier cares about most and what most "satellite tools" ignore.
9. **Chain of custody** — segregation vs. mass balance at silo / crusher / port; link lots to plots.
10. **DDS submission** — TRACES API; reference-number management; downstream referencing.
11. **Continuous monitoring** — re-screen the plot base on new RADD / GLAD / DETER alerts; notify.

**Non-functional that matter here**
- Audit-grade: every verdict reproducible (dataset version, algorithm version, analyst, timestamp).
- Multi-tenant with strict isolation (CU clients are competitors; farmers' polygons are commercially sensitive).
- Scale: one trader can have thousands of plots of hundreds–thousands of ha each; Brazil soya ≈ 45 M ha total. Screening must be batch and cheap; imagery only pulled for AMBER/RED and for evidence.
- Languages: EN / PT-BR / ES.
- Retention 5 years; LGPD + GDPR.
- Commodity-agnostic architecture — CU will want cocoa / coffee / palm / rubber / wood next; the engine is the same, only the legality layers and forest-type nuances differ.

## 7. Hard problems to be honest about

1. **Cerrado.** Most new Brazilian soya expansion is in the Cerrado (MATOPIBA). Much of it isn't "forest" under EUDR, so the product may correctly say GREEN while NGOs and buyers say the soya is from converted native vegetation. CU needs to decide whether to also report "native vegetation conversion" as a separate flag (e.g. for RTRS / Cefetra CRS / buyer policies). Recommend: **two flags — EUDR-forest and native-vegetation** — so the legal answer and the reputational answer are both visible.
2. **Baseline disagreement.** JRC GFC 2020, Hansen and WorldCover disagree at plot edges. Need a documented rule (e.g. JRC primary, Hansen/S2 for tie-break) and human review where they conflict.
3. **Plot precision.** A CAR polygon covers the whole property including the legal reserve. One hectare of reserve cleared in 2022 turns a 5,000 ha GREEN farm RED. The product must let suppliers submit **field-level** polygons and must show the client exactly what the overlap is, rather than silently failing the plot.
4. **False positives** from harvest, fire, drought, cloud shadow, eucalyptus/tree-crop rotations. Time-series + radar + analyst gate — never fully automatic RED.
5. **Polygon acquisition.** Farmers won't hand over polygons easily; traders often only have the silo, not the farm. The product should make CAR-based onboarding trivial (search by CAR number → fetch polygon → confirm).
6. **Timeline.** 15 weeks to application date. Ship the screening + evidence + review loop first; risk/legality/DDS modules after. Build on Earth Engine / Copernicus, don't train models.
7. **Liability.** CU is putting its accreditation behind a verdict. Methodology document, versioned, is a deliverable — not just software.

## 8. Suggested MVP (to validate with CU)

Upload polygons → automated screening against JRC GFC 2020 + Hansen + RADD/GLAD + PRODES → per-plot GREEN/AMBER/RED with dated Sentinel-2 before/after chips and NDVI/S1 time series → analyst review & sign-off → evidence PDF + DDS-ready GeoJSON/CSV export. Single tenant (one CU office, one pilot client), Brazil first.

## 9. Questions to put to Control Union

1. Who is the primary user — CU auditors verifying clients, or CU's clients self-serving on a CU-branded platform? Both?
2. What does CU deliver to its client at the end — a verification statement, an audit report, an input into RTRS/ISCC/ProTerra/Cefetra CRS audits?
3. Which origins first — Brazil (which states/biomes), Argentina, Paraguay, Uruguay, India, US?
4. Volume: how many clients, suppliers, plots, hectares in season 1? Peak timing?
5. Where do polygons come from today — CAR, client GIS, nothing? Do they need a field-capture mobile app?
6. Scope: deforestation only, or deforestation + legality + Art. 10 risk assessment?
7. Do they want DDS submission to TRACES, or only the evidence for their client's own filing?
8. Should the platform also flag non-EUDR conversion (Cerrado native vegetation, Soy Moratorium 2008 cut-off)?
9. Budget for commercial imagery, or free Sentinel/Landsat only?
10. What happens on RED — supplier exclusion, CAPA, re-audit? Who decides?
11. Existing tools or partners (Global Forest Watch Pro, Satelligence, LiveEO, Orbify, Meridia)? Is this build, buy, or integrate?
12. Other commodities on the roadmap?
13. Data ownership, confidentiality, hosting region (EU / Brazil), LGPD/GDPR posture.

## Sources
- Commission, 13 Jul 2026: https://environment.ec.europa.eu/news/commission-updates-product-scope-and-tools-support-eudr-2026-07-13_en
- Hogan Lovells on simplification package: https://www.hoganlovells.com/en/publications/eu-deforestation-regulation-commission-publishes-simplification-package-ahead-of-december-2026
- Adherent, simplification review 2026: https://www.adherent.com/blog/eudr-simplification-review-2026-whats-new-what-stays-the-same-and-what-additional-support-can-companies-expect/
- EUSTAFOR on 4 May 2026 package: https://eustafor.eu/eudr-what-the-commissions-4-may-2026-simplification-package-means-for-wood-state-forests-and-non-eu-operators/
- Stibbe, the amended EUDR: https://www.stibbe.com/publications-and-insights/the-amended-eudr-what-has-changed-and-what-has-remained
- Country benchmarking (Preferred by Nature): https://www.preferredbynature.org/news/european-commission-publishes-first-list-country-benchmarks-under-eu-deforestation-regulation
- Country classification list (Commission): https://green-forum.ec.europa.eu/nature-and-biodiversity/deforestation-regulation-implementation/eudr-cooperation-and-partnerships/country-classification-list_en
- Control Union EUDR page: https://www.controlunion.com/eu-deforestation-regulation-eudr/
- Meridia, EUDR soy guide: https://www.meridia.land/blog/eudr-soy-compliance-a-comprehensive-guide
- Geolocation rules (Global Traceability FAQ): https://www.global-traceability.com/en/faqs-explained-eudr-traceability-geolocation-4th-ed/
