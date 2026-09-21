"""The audit dossier — a self-contained PDF record of one analysis.

The dossier is the artifact a forester, auditor or regulator keeps. It has to
stand alone, so it restates every input, every model choice and every caveat,
and it leads with the data mode: a simulated run is stamped as such on the
first page, not buried in a footnote.
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.analysis.pipeline import AnalysisResult
from app.providers.base import DataMode
from app.science.change import ChangeResult
from app.science.confidence import COMPONENT_ORDER, WEIGHTS

INK = colors.HexColor("#0f1720")
MUTED = colors.HexColor("#5b6674")
LINE = colors.HexColor("#d3dae2")
ACCENT = colors.HexColor("#1f7d4f")
WARN_BG = colors.HexColor("#fff4e5")
WARN_INK = colors.HexColor("#8a4b00")
PANEL = colors.HexColor("#f4f7f9")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "SSTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=22, leading=26, textColor=INK, alignment=TA_LEFT, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "SSSubtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=MUTED, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "SSH2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11.5, leading=15, textColor=INK, spaceBefore=12, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "SSBody", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, leading=13, textColor=INK, spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "SSSmall", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.8, leading=11, textColor=MUTED,
        ),
        "warn": ParagraphStyle(
            "SSWarn", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9.5, leading=13.5, textColor=WARN_INK,
        ),
        "metric": ParagraphStyle(
            "SSMetric", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=17, leading=20, textColor=INK,
        ),
        "metriclabel": ParagraphStyle(
            "SSMetricLabel", parent=base["Normal"], fontName="Helvetica",
            fontSize=7, leading=9, textColor=MUTED,
        ),
    }


def _kv_table(rows: list[tuple[str, str]], width: float) -> Table:
    table = Table(
        [[Paragraph(f"<b>{k}</b>", _styles()["body"]), Paragraph(v, _styles()["body"])]
         for k, v in rows],
        colWidths=[width * 0.34, width * 0.66],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _data_table(header: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    st = _styles()
    data = [[Paragraph(f"<b>{h}</b>", st["small"]) for h in header]]
    data += [[Paragraph(str(c), st["small"]) for c in row] for row in rows]
    table = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PANEL),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _metric_row(cards: list[tuple[str, str, str]], width: float) -> Table:
    st = _styles()
    cells = []
    for label, value, sub in cards:
        cells.append(
            [
                Paragraph(label.upper(), st["metriclabel"]),
                Paragraph(value, st["metric"]),
                Paragraph(sub, st["metriclabel"]),
            ]
        )
    inner = [
        Table([[c[0]], [c[1]], [c[2]]], colWidths=[width / len(cards) - 6])
        for c in cells
    ]
    for t in inner:
        t.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
    outer = Table([inner], colWidths=[width / len(cards)] * len(cards), hAlign="LEFT")
    outer.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return outer


def _warning_block(text: str, width: float) -> Table:
    st = _styles()
    table = Table([[Paragraph(text, st["warn"])]], colWidths=[width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
                ("BOX", (0, 0), (-1, -1), 0.8, WARN_INK),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return table


def _footer(canvas, doc) -> None:  # noqa: ANN001 — reportlab callback signature
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        18 * mm, 12 * mm, "SylvaSense forest carbon audit dossier"
    )
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
    canvas.restoreState()


def build_dossier(
    result: AnalysisResult, change: ChangeResult | None = None
) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=f"SylvaSense dossier {result.aoi.aoi_id}",
        author="SylvaSense",
        subject="Forest carbon audit dossier",
    )
    width = doc.width
    summary = result.summary()
    prov = result.provenance()
    model = prov["model"]
    simulated = result.mode == DataMode.SANDBOX_SIMULATION
    story: list[Any] = []

    # --- Header ---------------------------------------------------------
    story.append(Paragraph("SylvaSense", st["title"]))
    story.append(
        Paragraph(
            f"Forest carbon audit dossier &nbsp;·&nbsp; AOI <b>{result.aoi.aoi_id}</b> "
            f"&nbsp;·&nbsp; epoch <b>{result.year}</b> &nbsp;·&nbsp; generated "
            f"{dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            st["subtitle"],
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.1, color=ACCENT, spaceAfter=10))

    if simulated:
        story.append(
            _warning_block(
                "SANDBOX SIMULATION — NOT AN OBSERVATION<br/><br/>"
                "No Earth Engine credential was configured, so these figures were "
                "produced by SylvaSense's forward model rather than measured by "
                "Sentinel-2, Sentinel-1 or GEDI. They exercise the analysis pipeline "
                "and must not be used for carbon accounting, reporting, trading or "
                "any operational decision.<br/><br/>"
                "To produce real observations, configure an Earth Engine service "
                "account (see docs/EARTH_ENGINE_SETUP.md) and re-run this analysis.",
                width,
            )
        )
        story.append(Spacer(1, 10))

    # --- Headline metrics -------------------------------------------------
    b = summary["biomass"]
    c = summary["carbon"]
    co2 = summary["co2e"]
    story.append(
        _metric_row(
            [
                ("Canopy cover", f"{summary['canopy']['cover_pct']:.1f}%", "scaled NDVI"),
                (
                    "Aboveground biomass",
                    f"{b['mean_mg_ha']:.0f}",
                    f"Mg/ha · 90% CI {b['p05_mg_ha']:.0f}–{b['p95_mg_ha']:.0f}",
                ),
                ("Carbon", f"{c['mean_tc_ha']:.1f}", "tC/ha · IPCC CF 0.47"),
                ("CO<sub>2</sub> equivalent", f"{co2['mean_tco2e_ha']:.1f}", "tCO<sub>2</sub>e/ha"),
            ],
            width,
        )
    )
    story.append(Spacer(1, 6))

    # --- Area of interest --------------------------------------------------
    lon, lat = result.aoi.centroid()
    story.append(Paragraph("Area of interest", st["h2"]))
    story.append(
        _kv_table(
            [
                ("AOI identifier", result.aoi.aoi_id),
                ("Area", f"{result.aoi.area_km2:,.2f} km² ({result.aoi.area_ha:,.0f} ha)"),
                ("Centroid", f"{lat:.5f}, {lon:.5f}"),
                (
                    "Bounding box",
                    ", ".join(f"{v:.5f}" for v in result.aoi.bounds.as_list()),
                ),
                (
                    "Analysis grid",
                    f"{prov['grid']['rows']} × {prov['grid']['cols']} cells at "
                    f"{prov['grid']['cell_size_m']:.0f} m "
                    f"({prov['grid']['cell_area_ha']:.2f} ha per cell)",
                ),
                ("Observation window", f"{prov['window']['start']} to {prov['window']['end']}"),
                ("Area measurement", "Geodesic on the WGS84 ellipsoid (pyproj.Geod)"),
            ],
            width,
        )
    )

    # --- Carbon stock ------------------------------------------------------
    story.append(Paragraph("Carbon stock over the area of interest", st["h2"]))
    story.append(
        _kv_table(
            [
                ("Total aboveground biomass", f"{b['total_stock_mg']:,.0f} Mg"),
                ("Total aboveground carbon", f"{c['total_tc']:,.0f} tC"),
                ("Total CO<sub>2</sub> equivalent", f"{co2['total_tco2e']:,.0f} tCO<sub>2</sub>e"),
                (
                    "Belowground carbon (inferred)",
                    f"{summary['belowground']['mean_tc_ha']:.1f} tC/ha — "
                    f"IPCC root-to-shoot {summary['belowground']['root_to_shoot']}, "
                    "not observed and excluded from the figures above",
                ),
                (
                    "Conversion constants",
                    f"Carbon fraction {summary['constants']['carbon_fraction']} "
                    f"({summary['constants']['carbon_fraction_source']}); "
                    f"CO<sub>2</sub>:C {summary['constants']['co2e_per_carbon']:.4f}",
                ),
            ],
            width,
        )
    )

    # --- Model -------------------------------------------------------------
    story.append(Paragraph("Model and calibration", st["h2"]))
    model_rows = [
        ("Model version", model["version"]),
        ("Calibration", model["calibration"]),
        ("Algorithm", model["algorithm"]),
        ("Training samples", f"{model['n_training']:,}"),
        ("Training source", model["training_source"]),
    ]
    if model["cv_r2"] is not None:
        model_rows.append(
            (
                "Cross-validated skill",
                f"R² = {model['cv_r2']:.2f}, RMSE = {model['cv_rmse']:.1f} Mg/ha "
                f"over {model['cv_folds']} folds",
            )
        )
        model_rows.append(("Validation scheme", model["cv_scheme"] or "—"))
    else:
        model_rows.append(
            ("Cross-validated skill", "Not applicable — no local calibration was fitted")
        )
    if model["saturation_note"]:
        model_rows.append(("Saturation", model["saturation_note"]))
    model_rows.append(
        (
            "Predictors",
            ", ".join(model["features"]) if model["features"] else "—",
        )
    )
    story.append(_kv_table(model_rows, width))

    if model["uncalibrated"]:
        story.append(Spacer(1, 6))
        story.append(
            _warning_block(
                "UNCALIBRATED ESTIMATE — this area had too few GEDI reference "
                "footprints to fit a local model, so a published regional "
                "relationship was used instead. It is suitable for prioritising "
                "survey effort, not for carbon accounting.",
                width,
            )
        )

    if model["feature_importance"]:
        top = list(model["feature_importance"].items())[:8]
        story.append(Spacer(1, 6))
        story.append(
            _data_table(
                ["Predictor", "Relative importance"],
                [[k, f"{v * 100:.1f}%"] for k, v in top],
                [width * 0.5, width * 0.5],
            )
        )

    if model["caveats"]:
        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>Caveats recorded by the model</b>", st["body"]))
        for caveat in model["caveats"]:
            story.append(Paragraph(f"• {caveat}", st["small"]))

    # --- Data sources -------------------------------------------------------
    story.append(Paragraph("Input data and provenance", st["h2"]))
    source_rows = []
    for key, label in (
        ("optical", "Optical"),
        ("radar", "Radar"),
        ("gedi", "Biomass reference"),
        ("terrain", "Terrain"),
        ("landcover", "Land cover"),
    ):
        entry = prov.get(key)
        if entry is None:
            source_rows.append([label, "—", "Not available for this area", "—"])
            continue
        if key == "gedi":
            detail = f"{entry['footprints']:,} footprints"
            span = f"{entry['first_date']} → {entry['last_date']}"
        elif key in ("optical", "radar"):
            detail = f"{entry['scenes']} scenes @ {entry['resolution_m']} m"
            span = f"{entry['first_date']} → {entry['last_date']}"
        else:
            detail = "—"
            span = str(entry.get("year", "—"))
        source_rows.append([label, entry["collection"], detail, span])

    story.append(
        _data_table(
            ["Role", "Collection", "Detail", "Date span"],
            source_rows,
            [width * 0.16, width * 0.36, width * 0.26, width * 0.22],
        )
    )

    story.append(Spacer(1, 4))
    audit_rows = [
        [
            s.label,
            s.status.value.replace("_", " ").title(),
            s.detail or "—",
        ]
        for s in result.audit.sources
    ]
    story.append(Paragraph("Availability at audit time", st["h2"]))
    story.append(
        _data_table(
            ["Source", "Status", "Detail"],
            audit_rows,
            [width * 0.30, width * 0.16, width * 0.54],
        )
    )

    # --- Confidence -----------------------------------------------------------
    conf = summary["confidence"]
    frac = conf["class_fractions"]
    confidence_block: list[Any] = [
        Paragraph("Confidence", st["h2"]),
        Paragraph(
            f"Mean confidence across the area is <b>{conf['mean_score']:.2f}</b>. "
            "Confidence combines four measured properties of the evidence, weighted "
            "as shown; it is not a restatement of the model interval alone.",
            st["body"],
        ),
        Spacer(1, 4),
    ]
    confidence_block.append(
        _data_table(
            ["Confidence class", "Share of area", "Meaning"],
            [
                [
                    "High confidence",
                    f"{frac['HIGH_CONFIDENCE'] * 100:.1f}%",
                    "Estimate is well supported by the available evidence",
                ],
                [
                    "Survey recommended",
                    f"{frac['SURVEY_RECOMMENDED'] * 100:.1f}%",
                    "Evidence is thin — ground measurement would materially help",
                ],
                [
                    "Insufficient data",
                    f"{frac['INSUFFICIENT_DATA'] * 100:.1f}%",
                    "Not enough evidence to stand behind a value here",
                ],
            ],
            [width * 0.28, width * 0.18, width * 0.54],
        )
    )
    confidence_block.append(Spacer(1, 4))
    confidence_block.append(
        _data_table(
            ["Confidence component", "Weight"],
            [[k.replace("_", " ").title(), f"{WEIGHTS[k] * 100:.0f}%"] for k in COMPONENT_ORDER],
            [width * 0.6, width * 0.4],
        )
    )
    story.append(KeepTogether(confidence_block))

    # --- Field plan -------------------------------------------------------------
    plan = result.field_plan
    story.append(Paragraph("Recommended field survey", st["h2"]))
    if not plan.sites:
        story.append(
            Paragraph("No survey sites could be placed for this area.", st["body"])
        )
    else:
        story.append(
            Paragraph(
                f"{len(plan.sites)} sites, minimum separation "
                f"{plan.min_separation_m:,.0f} m, together addressing "
                f"{plan.total_expected_reduction_pct:.1f}% of the area's total biomass "
                f"variance. {plan.method}.",
                st["body"],
            )
        )
        story.append(Spacer(1, 4))
        story.append(
            _data_table(
                ["#", "Latitude", "Longitude", "Priority", "AGB ± SD (Mg/ha)", "Var. addressed", "Limiting factor"],
                [
                    [
                        f"{s.index:02d}",
                        f"{s.lat:.5f}",
                        f"{s.lon:.5f}",
                        s.priority,
                        f"{s.agb_pred_mg_ha:.0f} ± {s.agb_sd_mg_ha:.0f}",
                        f"{s.expected_variance_reduction_pct:.2f}%",
                        s.reason,
                    ]
                    for s in plan.sites
                ],
                [
                    width * 0.05, width * 0.11, width * 0.11, width * 0.10,
                    width * 0.16, width * 0.12, width * 0.35,
                ],
            )
        )

    # --- Change ---------------------------------------------------------------
    if change is not None:
        cd = change.as_dict()
        story.append(
            KeepTogether(
                [
                    Paragraph("Temporal change", st["h2"]),
                    Paragraph(
                        f"<b>{cd['verdict'].replace('_', ' ')}</b> — {cd['verdict_detail']}",
                        st["body"],
                    ),
                    Spacer(1, 6),
                    _kv_table(
                        [
                            ("Epochs compared", f"{change.year_from} → {change.year_to}"),
                            (
                                "Mean biomass",
                                f"{cd['biomass']['from_mg_ha']:.1f} → "
                                f"{cd['biomass']['to_mg_ha']:.1f} Mg/ha "
                                f"(Δ {cd['biomass']['delta_mg_ha']:+.1f}, 95% CI "
                                f"{cd['biomass']['delta_p05_mg_ha']:+.1f} to "
                                f"{cd['biomass']['delta_p95_mg_ha']:+.1f})",
                            ),
                            (
                                "Mean carbon",
                                f"{cd['carbon']['from_tc_ha']:.1f} → "
                                f"{cd['carbon']['to_tc_ha']:.1f} tC/ha "
                                f"(Δ {cd['carbon']['delta_tc_ha']:+.1f})",
                            ),
                            (
                                "Significance test",
                                f"{cd['statistics']['test']}: z = "
                                f"{cd['statistics']['z_score']:.2f}, p = "
                                f"{cd['statistics']['p_value']:.4f}, "
                                f"critical |z| = {cd['statistics']['z_critical']:.2f}",
                            ),
                            (
                                "Area with significant loss",
                                f"{cd['areas']['significant_loss_ha']:,.0f} ha",
                            ),
                            (
                                "Area with significant gain",
                                f"{cd['areas']['significant_gain_ha']:,.0f} ha",
                            ),
                            (
                                "Materiality floor",
                                f"{change.evidence['materiality_floor_mg_ha']:.0f} Mg/ha — "
                                "changes smaller than this are not reported even when "
                                "statistically detectable",
                            ),
                        ],
                        width,
                    ),
                ]
            )
        )

    # --- Method notes -----------------------------------------------------------
    method_block: list[Any] = [Paragraph("Method notes and references", st["h2"])]
    for line in (
        "Areas, perimeters and inter-site distances are geodesic on the WGS84 "
        "ellipsoid, not planar approximations of degrees.",
        "Fractional canopy cover is retrieved from scaled NDVI — Carlson &amp; Ripley "
        "(1997), Gutman &amp; Ignatov (1998).",
        "Biomass prediction intervals come from independently fitted quantile "
        "regressors at α = 0.05 and 0.95; they are not symmetric error bars.",
        "Model skill is reported from spatially blocked cross-validation. Random "
        "k-fold over spatially autocorrelated footprints reports optimistic scores.",
        "The area-mean interval uses an effective sample size derived from spatial "
        "blocks, because neighbouring cells do not carry independent errors.",
        "Carbon fraction 0.47 — IPCC 2006 Guidelines, Vol. 4, Ch. 4, Table 4.3.",
        "Change significance is a two-sided z-test on the difference of two area "
        "means, gated by a materiality floor.",
        "Dual-pol radar vegetation index — Kim &amp; van Zyl (2009). Water Cloud "
        "Model — Attema &amp; Ulaby (1978).",
    ):
        method_block.append(Paragraph(f"• {line}", st["small"]))
    story.append(KeepTogether(method_block))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LINE, spaceAfter=6))
    story.append(
        Paragraph(
            f"Data mode: <b>{result.mode.value}</b> &nbsp;·&nbsp; analysis created "
            f"{result.created_at} &nbsp;·&nbsp; SylvaSense audit dossier",
            st["small"],
        )
    )

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
