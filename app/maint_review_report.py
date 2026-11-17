"""Breakdown Maintenance Review — email builder.

Mirrors the graphical "Report" tab (app/templates/maint.html) for email. Email
clients cannot run Chart.js, so the charts are rendered as static images by
QuickChart (quickchart.io) — the recipient's mail client loads each <img>, so
no server-side rendering or Vercel egress is needed. KPIs, the monthly cost
table and the key observations are plain HTML, plus a button to the live,
interactive report.

The figures are the Jul–Oct 2026 review (source: Smaac Maintenance Resolution &
Maintenance Reports). Keep these in sync with the REPORT data in maint.html.
"""
import json
import urllib.parse

# --- figures (same numbers as the Report tab) --------------------------------
PERIOD = "July – October 2026"
KPIS = [
    ("Breakdowns logged", "23"),
    ("Total downtime", "12h 59m"),
    ("Avg per breakdown", "34 min"),
    ("Spares issued", "₹24,802"),
]
SUBLINE = ("10 resolved and 13 closed · 21 Medium and 2 High priority · "
           "Longest single stoppage 1h 25m (Arc Welding-03, 14 Jul).")

BD_MONTH = (["Jul", "Aug", "Sep", "Oct"], [8, 4, 6, 5])
SPARE_MONTH = (["Jul", "Aug", "Sep", "Oct"], [430, 0, 13072, 11300])
BD_GROUP = (["Arc welding", "Airless spray", "Angle grinders", "Cut-off", "Others"],
            [6, 5, 5, 2, 5])
DT_GROUP = (["Cut-off", "Airless spray", "Others", "Grinders", "Arc welding"],
            [79, 115, 145, 170, 270])

COST_ROWS = [
    ("July 2026", "2", "ARC Welding-01, -07", "430", "1.7%"),
    ("September 2026", "5", "Airless Spray, AG-5 Grinder-01, AG-4 Grinder-05, ARC Welding-09/-07/-03", "13,072", "52.7%"),
    ("October 2026", "3", "Airless Spray, AG-4 Grinder-03", "11,300", "45.6%"),
    ("TOTAL", "10", "", "24,802", "100%"),
]
OBSERVATIONS = [
    "July peak: 8 breakdowns, 5 of them electrical (arc welding, compressor, grinder, cut-off).",
    "October: 5 breakdowns, including both High-priority armature failures on 12 Oct.",
    "Airless spray tip, filter and strainer damage recurs in Aug, Sep and Oct.",
    "Spares issued — Airless spray ₹12,067 · Angle grinders ₹11,190 · Arc welding ₹1,545.",
]

NAVY = "#0A2B66"
BLUE = "#01578C"
AMBER = "#E19619"
RED = "#dc2626"


def _qc(cfg: dict, w: int = 500, h: int = 280) -> str:
    """Build a QuickChart image URL from a Chart.js config."""
    c = urllib.parse.quote(json.dumps(cfg, separators=(",", ":")))
    return (f"https://quickchart.io/chart?bkg=white&w={w}&h={h}"
            f"&devicePixelRatio=2&c={c}")


def _bar(labels, data, color, title, horizontal=False, prefix=""):
    cfg = {
        "type": "bar",
        "data": {"labels": labels,
                 "datasets": [{"label": title, "data": data,
                               "backgroundColor": color, "borderRadius": 4}]},
        "options": {
            "indexAxis": "y" if horizontal else "x",
            "plugins": {"legend": {"display": False},
                        "title": {"display": True, "text": title,
                                  "font": {"size": 15, "weight": "bold"}}},
        },
    }
    return _qc(cfg)


def charts() -> list:
    """(caption, image_url) for the email, in order."""
    return [
        ("Breakdowns by month", _bar(*BD_MONTH, BLUE, "Breakdowns by month")),
        ("Spares cost per month (₹)", _bar(*SPARE_MONTH, AMBER, "Spares cost per month (INR)")),
        ("Breakdowns by machine group", _bar(*BD_GROUP, BLUE, "Breakdowns by machine group")),
        ("Downtime by machine group (min)", _bar(*DT_GROUP, RED, "Downtime by machine group (min)", horizontal=True)),
    ]


def build_email(view_url: str = "https://app.metfraa.com/maint") -> tuple:
    """Return (subject, html, text) for the maintenance review report."""
    kpi_html = "".join(
        f"<td style='padding:10px 14px;border:1px solid #e2e8f0;vertical-align:top'>"
        f"<div style='font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:#6b7689'>{lbl}</div>"
        f"<div style='font-size:22px;font-weight:700;color:#0d1421;margin-top:2px'>{val}</div></td>"
        for lbl, val in KPIS)

    chart_html = "".join(
        f"<tr><td style='padding:10px 0'>"
        f"<img src='{url}' alt='{cap}' width='500' "
        f"style='max-width:100%;border:1px solid #e2e8f0;border-radius:8px'></td></tr>"
        for cap, url in charts())

    cost_html = ""
    for i, (mon, vch, mc, amt, share) in enumerate(COST_ROWS):
        bold = ";font-weight:700" if mon == "TOTAL" else ""
        cost_html += (
            "<tr>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0{bold}'>{mon}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0{bold}'>{vch}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;color:#64748b;font-size:12px'>{mc}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right{bold}'>{amt}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right{bold}'>{share}</td></tr>")

    obs_html = "".join(f"<li style='margin-bottom:5px'>{o}</li>" for o in OBSERVATIONS)

    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;color:#0d1421;max-width:760px">
  <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#6b7689">Breakdown Maintenance Review</div>
  <h2 style="margin:4px 0 2px;font-size:20px">Equipment &amp; machinery — {PERIOD}</h2>
  <p style="margin:0 0 14px;color:#64748b;font-size:12px">Metfraa Steel Buildings Pvt. Ltd. · Source: Smaac Maintenance Resolution &amp; Maintenance Reports</p>

  <table style="border-collapse:collapse;width:100%;margin-bottom:6px"><tr>{kpi_html}</tr></table>
  <p style="margin:0 0 16px;color:#64748b;font-size:12px">{SUBLINE}</p>

  <table style="border-collapse:collapse;width:100%">{chart_html}</table>

  <h3 style="font-size:15px;margin:18px 0 8px">Monthly cost detail</h3>
  <table style="border-collapse:collapse;font-size:13px;width:100%">
    <thead><tr style="background:{NAVY};color:#fff">
      <th style="padding:6px 10px;border:1px solid {NAVY};text-align:left">Month</th>
      <th style="padding:6px 10px;border:1px solid {NAVY};text-align:left">Vouchers</th>
      <th style="padding:6px 10px;border:1px solid {NAVY};text-align:left">Machines</th>
      <th style="padding:6px 10px;border:1px solid {NAVY};text-align:right">Amount (₹)</th>
      <th style="padding:6px 10px;border:1px solid {NAVY};text-align:right">Share</th>
    </tr></thead><tbody>{cost_html}</tbody></table>

  <h3 style="font-size:15px;margin:18px 0 8px">Key observations</h3>
  <ul style="font-size:13px;color:#334155;padding-left:18px;margin:0 0 16px">{obs_html}</ul>

  <a href="{view_url}" style="display:inline-block;background:{BLUE};color:#fff;text-decoration:none;font-weight:700;font-size:13px;padding:10px 18px;border-radius:8px">View the interactive report</a>
  <p style="color:#94a3b8;font-size:12px;margin-top:16px">Metfraa Steel Buildings — automated maintenance review.</p>
</div>"""

    text = (f"Breakdown Maintenance Review — {PERIOD}\n"
            + " · ".join(f"{l}: {v}" for l, v in KPIS) + "\n"
            + SUBLINE + f"\n\nInteractive report: {view_url}")
    subject = f"Breakdown Maintenance Review — {PERIOD}"
    return subject, html, text
