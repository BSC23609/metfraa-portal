"""Generate the monthly performance PDF report — Metfraa branded.

v2 rewrite (Sub-batch 5): reads from MonthlyKPIActual instead of the legacy
DailyEntry/KPIEntry tables.

Sections:
- Cover with employee info + final weighted score
- KPI scorecard table
- KPI achievement bar chart
- Sections that require daily/attendance data are omitted (nothing to show
  in v2 — the daily task report system replaces per-day tracking).
"""
import io
import calendar
import os
from datetime import datetime

import os as _os
if _os.getenv("VERCEL") and not _os.environ.get("MPLCONFIGDIR"):
    _os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"  # read-only fs except /tmp
import matplotlib
matplotlib.use("Agg")  # noqa
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)

from ..models import Employee, KPI, MonthlyKPIActual
from ..routes.monthly_kpi import compute_weighted_score

METFRAA_BLUE = colors.HexColor("#3B82F6")
METFRAA_BLACK = colors.HexColor("#0A0A0A")
METFRAA_GRAY = colors.HexColor("#6B7280")
LIGHT_GRAY = colors.HexColor("#F3F4F6")
SUCCESS = colors.HexColor("#10B981")
WARNING = colors.HexColor("#F59E0B")
DANGER = colors.HexColor("#EF4444")

LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "img", "metfraa_logo.png")


def _score_color(score: float):
    if score >= 80: return SUCCESS
    if score >= 60: return WARNING
    return DANGER


def _build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=base["Heading1"],
            fontSize=22, textColor=METFRAA_BLACK,
            alignment=TA_CENTER, spaceAfter=4, fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "Sub", parent=base["Normal"],
            fontSize=11, textColor=METFRAA_GRAY,
            alignment=TA_CENTER, spaceAfter=20, fontName="Helvetica",
        ),
        "section": ParagraphStyle(
            "Section", parent=base["Heading2"],
            fontSize=14, textColor=METFRAA_BLUE,
            spaceBefore=14, spaceAfter=8, fontName="Helvetica-Bold",
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"],
            fontSize=10, textColor=METFRAA_BLACK,
            spaceAfter=6, fontName="Helvetica",
        ),
        "small": ParagraphStyle(
            "Small", parent=base["Normal"],
            fontSize=9, textColor=METFRAA_GRAY,
            fontName="Helvetica",
        ),
    }


def _make_chart_kpi_achievement(rows: list) -> bytes:
    """Horizontal bar chart of KPI achievement %.

    rows: list of dicts with keys `name`, `achievement_pct`
    """
    if not rows:
        # Empty placeholder chart
        fig, ax = plt.subplots(figsize=(8.5, 2.5), dpi=120)
        ax.text(0.5, 0.5, "No KPI data submitted for this month",
                ha="center", va="center", fontsize=11, color="#6B7280")
        ax.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    names = [(r["name"][:35] + "...") if len(r["name"]) > 35 else r["name"] for r in rows]
    pct = [r["achievement_pct"] for r in rows]
    colors_list = ["#10B981" if p >= 80 else "#F59E0B" if p >= 60 else "#EF4444" for p in pct]

    fig, ax = plt.subplots(figsize=(8.5, max(3.0, 0.45 * len(rows) + 1.5)), dpi=120)
    y_pos = range(len(names))
    ax.barh(y_pos, pct, color=colors_list, edgecolor="white", height=0.65)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Achievement %", fontsize=9, color="#374151")
    ax.invert_yaxis()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D1D5DB")
    ax.spines["bottom"].set_color("#D1D5DB")
    ax.tick_params(colors="#374151")
    for i, v in enumerate(pct):
        ax.text(v + 1.5, i, f"{v:.1f}%", va="center", fontsize=8, color="#374151")
    ax.grid(axis="x", linestyle="--", alpha=0.4, color="#D1D5DB")
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _header_footer(canvas, doc):
    """Branded header (logo) + footer on every page."""
    canvas.saveState()
    width, height = A4

    canvas.setFillColor(METFRAA_BLACK)
    canvas.rect(0, height - 18 * mm, width, 18 * mm, stroke=0, fill=1)
    canvas.setFillColor(METFRAA_BLUE)
    canvas.rect(0, height - 19 * mm, width, 1 * mm, stroke=0, fill=1)

    if os.path.exists(LOGO_PATH):
        try:
            canvas.drawImage(
                LOGO_PATH,
                10 * mm, height - 16 * mm,
                width=40 * mm, height=12 * mm,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            canvas.setFillColor(colors.white)
            canvas.setFont("Helvetica-Bold", 14)
            canvas.drawString(10 * mm, height - 12 * mm, "METFRAA")
    else:
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(10 * mm, height - 12 * mm, "METFRAA")

    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(width - 10 * mm, height - 11 * mm, "Steeling the Future")
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(width - 10 * mm, height - 15 * mm, "Monthly KPI Performance Report")

    canvas.setFillColor(METFRAA_GRAY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(10 * mm, 8 * mm,
                      f"Generated {datetime.now().strftime('%d %b %Y, %H:%M')} • Metfraa Steel Buildings Pvt. Ltd.")
    canvas.drawRightString(width - 10 * mm, 8 * mm, f"Page {doc.page}")

    canvas.restoreState()


def _load_data(db, employee_id: int, year: int, month: int) -> dict:
    """Load employee, KPI catalog, actuals, and compute score."""
    emp = db.query(Employee).filter_by(id=employee_id).first()
    if not emp:
        raise ValueError(f"Employee {employee_id} not found")

    actuals = (
        db.query(MonthlyKPIActual)
        .filter_by(employee_id=employee_id, year=year, month=month)
        .all()
    )
    kpis_by_id = {k.id: k for k in db.query(KPI).filter_by(employee_id=employee_id).all()}

    if actuals:
        result = compute_weighted_score(actuals)
        for row in result["rows"]:
            k = kpis_by_id.get(row["kpi_id"])
            row["name"] = k.name if k else "(deleted KPI)"
            row["unit"] = row["unit"] or (k.unit if k else "")
    else:
        # No submission — show all KPIs with 0 actuals so the table still shows structure
        rows = []
        for k in sorted(kpis_by_id.values(), key=lambda x: (x.display_order or 0, x.id)):
            rows.append({
                "kpi_id": k.id,
                "name": k.name,
                "unit": k.unit,
                "target": k.target,
                "weight": k.weight,
                "actual": 0.0,
                "achievement_pct": 0.0,
                "weighted_score": 0.0,
            })
        result = {"final_score": 0.0, "total_weight": sum(k.weight for k in kpis_by_id.values()), "rows": rows}

    return {"employee": emp, "final_score": result["final_score"],
            "total_weight": result["total_weight"], "rows": result["rows"],
            "submitted": bool(actuals)}


def generate_monthly_pdf(db, employee_id: int, year: int, month: int, generated_by: str = "system") -> bytes:
    """Generate the full monthly PDF report. Returns PDF bytes."""
    data = _load_data(db, employee_id, year, month)
    emp = data["employee"]
    month_label = f"{calendar.month_name[month]} {year}"

    styles = _build_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=28 * mm, bottomMargin=15 * mm,
        title=f"{emp.name} - KPI Report - {month_label}",
        author="Metfraa Steel Buildings",
    )

    elements = []

    # ---- Cover ----
    elements.append(Spacer(1, 18 * mm))
    elements.append(Paragraph("Monthly KPI Performance Report", styles["title"]))
    elements.append(Paragraph(month_label, styles["subtitle"]))
    elements.append(Spacer(1, 8 * mm))

    # Employee info card
    info_data = [
        ["Name:", emp.name],
        ["Employee Code:", emp.employee_code or "—"],
        ["Designation:", emp.designation or "—"],
        ["Department:", emp.department or "—"],
        ["Email:", emp.email or "—"],
        ["Reports To:", emp.reports_to or "—"],
        ["Reporting Period:", month_label],
    ]
    info_table = Table(info_data, colWidths=[45 * mm, 105 * mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), METFRAA_GRAY),
        ("TEXTCOLOR", (1, 0), (1, -1), METFRAA_BLACK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#E5E7EB")),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 12 * mm))

    # Final score box
    score = data["final_score"]
    sc_color = _score_color(score)
    score_paragraphs = [
        Paragraph("Final Weighted Score", ParagraphStyle(
            "ScoreLabel", fontSize=11, textColor=METFRAA_GRAY,
            alignment=TA_CENTER, fontName="Helvetica", leading=14,
        )),
        Spacer(1, 8),
        Paragraph(f"{score:.1f}", ParagraphStyle(
            "ScoreBig", fontSize=56, textColor=sc_color,
            alignment=TA_CENTER, fontName="Helvetica-Bold", leading=64,
        )),
        Spacer(1, 2),
        Paragraph("out of 100", ParagraphStyle(
            "ScoreOut", fontSize=11, textColor=METFRAA_GRAY,
            alignment=TA_CENTER, fontName="Helvetica", leading=14,
        )),
    ]
    score_box = Table([[score_paragraphs]], colWidths=[150 * mm])
    score_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.5, sc_color),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 18),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(score_box)

    # If not submitted, add a note under the score
    if not data["submitted"]:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(
            "<i>Employee has not yet submitted KPI actuals for this period. "
            "Table below shows KPI catalog with zero values.</i>",
            ParagraphStyle("NoSubNote", fontSize=9, textColor=DANGER,
                           alignment=TA_CENTER, fontName="Helvetica-Oblique",
                           leading=12)
        ))

    elements.append(PageBreak())

    # ---- KPI scorecard ----
    elements.append(Paragraph("KPI Scorecard", styles["section"]))
    elements.append(Paragraph(
        "Actual values submitted for the month, compared against monthly target. "
        "Each KPI has a weight (0–100%); weighted score = min(100%, achievement) × weight ÷ 100.",
        styles["small"]))
    elements.append(Spacer(1, 6))

    kpi_table_data = [["#", "KPI", "Unit", "Target", "Actual", "Achv. %", "Weight %", "Score"]]
    for i, r in enumerate(data["rows"], 1):
        target = r.get("target", 0)
        actual = r.get("actual", 0)
        kpi_table_data.append([
            str(i),
            r.get("name", ""),
            r.get("unit", ""),
            f"{target:g}",
            f"{actual:g}",
            f"{r['achievement_pct']:.1f}%",
            f"{r['weight']:g}",
            f"{r['weighted_score']:.2f}",
        ])
    kpi_table_data.append([
        "", "TOTAL", "", "", "",
        "",
        f"{data['total_weight']:g}",
        f"{score:.2f}"
    ])
    kpi_tbl = Table(
        kpi_table_data,
        colWidths=[10 * mm, 60 * mm, 15 * mm, 18 * mm, 18 * mm, 20 * mm, 18 * mm, 20 * mm]
    )
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), METFRAA_BLACK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -2), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT_GRAY]),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), METFRAA_BLUE),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
    ]))
    elements.append(kpi_tbl)
    elements.append(Spacer(1, 10 * mm))

    # ---- Chart: KPI Achievement ----
    elements.append(Paragraph("KPI Achievement Overview", styles["section"]))
    chart_bytes = _make_chart_kpi_achievement(data["rows"])
    # Height scales roughly with number of KPIs
    chart_h = min(120, max(50, 12 * len(data["rows"]) + 30))
    elements.append(Image(io.BytesIO(chart_bytes), width=170 * mm, height=chart_h * mm))

    elements.append(Spacer(1, 12 * mm))
    elements.append(Paragraph(
        f"<i>Report generated by {generated_by} on {datetime.now().strftime('%d %b %Y at %H:%M')}.</i>",
        styles["small"]))

    doc.build(elements, onFirstPage=_header_footer, onLaterPages=_header_footer)
    buf.seek(0)
    return buf.read()


def report_filename(employee, year: int, month: int) -> str:
    """Name_Designation_MMM_YYYY.pdf — sanitized."""
    name_part = "".join(c if c.isalnum() else "_" for c in (employee.name or "employee"))
    desig = (employee.designation or "").split("—")[0].strip() or "staff"
    desig_part = "".join(c if c.isalnum() else "_" for c in desig)
    month_str = calendar.month_abbr[month]
    return f"{name_part}_{desig_part}_{month_str}_{year}.pdf"
