"""
Generates the HTML evaluation report from eval_results.json.
Self-contained HTML with inline SVG charts.
"""
import json
import sys
import os
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def load_results():
    p = Path(__file__).parent / "eval_results.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def svg_bar(data, width=880, height=340, title=""):
    """Grouped bar chart comparing enhanced vs baseline."""
    n = len(data)
    bar_w = min(24, (width - 120) // (n * 3))
    gap = 6
    group_w = bar_w * 2 + gap + 16
    chart_l, chart_r = 55, 20
    chart_t, chart_b = 45, height - 55
    ch = chart_b - chart_t

    lines = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"'
             f' style="font-family:Inter,system-ui,sans-serif;background:#111827;'
             f'border-radius:12px;margin:12px 0;">']

    if title:
        lines.append(f'<text x="{width//2}" y="28" text-anchor="middle" fill="#e5e7eb"'
                     f' font-size="13" font-weight="600">{title}</text>')

    for p in [0, 25, 50, 75, 100]:
        y = chart_b - (p / 100) * ch
        lines.append(f'<line x1="{chart_l}" y1="{y}" x2="{width-chart_r}" y2="{y}"'
                     f' stroke="#1f2937" stroke-width="1"/>')
        lines.append(f'<text x="{chart_l-6}" y="{y+4}" text-anchor="end" fill="#6b7280"'
                     f' font-size="10">{p}</text>')

    for i, d in enumerate(data):
        x = chart_l + 15 + i * group_w
        ev, bv = min(d.get("e", 0), 100), min(d.get("b", 0), 100)

        # enhanced bar
        eh = (ev / 100) * ch
        lines.append(f'<rect x="{x}" y="{chart_b-eh}" width="{bar_w}" height="{max(eh,1)}"'
                     f' rx="3" fill="#06b6d4" opacity="0.9"/>')
        if ev > 0:
            lines.append(f'<text x="{x+bar_w//2}" y="{chart_b-eh-4}" text-anchor="middle"'
                         f' fill="#06b6d4" font-size="9" font-weight="700">{ev:.0f}</text>')

        # baseline bar
        bx = x + bar_w + gap
        bh = (bv / 100) * ch
        lines.append(f'<rect x="{bx}" y="{chart_b-bh}" width="{bar_w}" height="{max(bh,1)}"'
                     f' rx="3" fill="#f97316" opacity="0.85"/>')
        if bv > 0:
            lines.append(f'<text x="{bx+bar_w//2}" y="{chart_b-bh-4}" text-anchor="middle"'
                         f' fill="#f97316" font-size="9" font-weight="700">{bv:.0f}</text>')

        # label
        lines.append(f'<text x="{x+bar_w}" y="{chart_b+14}" text-anchor="middle"'
                     f' fill="#9ca3af" font-size="10" font-weight="500">{d["l"]}</text>')

    # legend
    lx = width - 240
    lines.append(f'<rect x="{lx}" y="16" width="10" height="10" rx="2" fill="#06b6d4"/>')
    lines.append(f'<text x="{lx+14}" y="25" fill="#d1d5db" font-size="10">Enhanced (MCP)</text>')
    lines.append(f'<rect x="{lx+120}" y="16" width="10" height="10" rx="2" fill="#f97316"/>')
    lines.append(f'<text x="{lx+134}" y="25" fill="#d1d5db" font-size="10">Baseline (grep)</text>')

    lines.append('</svg>')
    return '\n'.join(lines)


def generate_html(results):
    e_recalls = [r["enhanced"]["recall"] for r in results]
    b_recalls = [r["baseline"]["recall"] for r in results]
    e_avg = sum(e_recalls) / len(e_recalls)
    b_avg = sum(b_recalls) / len(b_recalls)

    wins = sum(1 for r in results if r["winner"] == "enhanced")
    losses = sum(1 for r in results if r["winner"] == "baseline")
    ties = sum(1 for r in results if r["winner"] == "tie")
    improvement = e_avg - b_avg

    # per-test chart
    test_data = [{"l": r["id"], "e": r["enhanced"]["recall"], "b": r["baseline"]["recall"]}
                 for r in results]

    # recall + precision charts
    prec_data = [{"l": r["id"],
                  "e": r["enhanced"]["precision"], "b": r["baseline"]["precision"]}
                 for r in results]

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Codebase Intelligence — A/B Evaluation Report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',system-ui,sans-serif;background:#030712;color:#e5e7eb;padding:40px 24px;line-height:1.6}}
.wrap{{max-width:920px;margin:0 auto}}
h1{{font-size:32px;font-weight:800;background:linear-gradient(135deg,#06b6d4,#8b5cf6);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}}
.sub{{color:#6b7280;font-size:14px;margin-bottom:32px}}
h2{{font-size:18px;color:#06b6d4;margin:36px 0 14px;padding-bottom:6px;border-bottom:1px solid #1f2937}}
.hero{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px;margin-bottom:24px}}
.hero-card{{background:#111827;border-radius:14px;padding:20px;text-align:center;border:1px solid #1f2937}}
.hero-card .big{{font-size:36px;font-weight:800}}
.hero-card .lbl{{color:#6b7280;font-size:11px;margin-top:2px;text-transform:uppercase;letter-spacing:0.5px}}
.cyan{{color:#06b6d4}} .orange{{color:#f97316}} .green{{color:#10b981}} .gray{{color:#6b7280}}
.purple{{color:#8b5cf6}}
.card{{background:#111827;border-radius:12px;padding:18px 20px;margin-bottom:14px;border:1px solid #1f2937}}
.card-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}
.card-head .q{{font-size:14px;font-weight:600;flex:1}}
.tag{{padding:3px 10px;border-radius:16px;font-size:11px;font-weight:600;white-space:nowrap}}
.tag-win{{background:rgba(6,182,212,0.15);color:#06b6d4}}
.tag-loss{{background:rgba(249,115,22,0.15);color:#f97316}}
.tag-tie{{background:rgba(107,114,128,0.15);color:#6b7280}}
.tid{{background:#1f2937;color:#06b6d4;padding:3px 8px;border-radius:6px;font-size:12px;
font-weight:600;margin-right:10px;white-space:nowrap}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.col{{background:#0a0f1a;border-radius:8px;padding:12px;font-size:13px}}
.col.enh{{border-left:3px solid #06b6d4}}
.col.bas{{border-left:3px solid #f97316}}
.col .title{{font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px}}
.col.enh .title{{color:#06b6d4}}
.col.bas .title{{color:#f97316}}
.row{{display:flex;justify-content:space-between;padding:2px 0;font-size:12px}}
.row .v{{font-weight:600}}
.pills{{display:flex;flex-wrap:wrap;gap:3px;margin-top:6px}}
.pill{{background:#1f2937;color:#9ca3af;padding:1px 7px;border-radius:3px;font-size:10px}}
.pill.hit{{background:rgba(6,182,212,0.2);color:#06b6d4}}
.gt{{color:#6b7280;font-size:11px;margin-top:8px}}
.gt b{{color:#9ca3af}}
.foot{{text-align:center;color:#374151;font-size:11px;margin-top:48px;padding-top:14px;
border-top:1px solid #1f2937}}
</style>
</head>
<body>
<div class="wrap">
<h1>Codebase Intelligence — A/B Evaluation</h1>
<p class="sub">Sparrow project · 57 files · 129 symbols · 15 real developer questions · Enhanced (MCP tools) vs Baseline (grep)</p>

<div class="hero">
  <div class="hero-card">
    <div class="big cyan">{e_avg:.1f}%</div>
    <div class="lbl">Enhanced Avg Recall</div>
  </div>
  <div class="hero-card">
    <div class="big orange">{b_avg:.1f}%</div>
    <div class="lbl">Baseline Avg Recall</div>
  </div>
  <div class="hero-card">
    <div class="big green">+{improvement:.1f}%</div>
    <div class="lbl">Improvement</div>
  </div>
  <div class="hero-card">
    <div class="big purple">{wins}-{losses}-{ties}</div>
    <div class="lbl">Win-Loss-Tie</div>
  </div>
</div>

<h2>Recall by Test Case</h2>
{svg_bar(test_data, title="Recall — how much of the answer did each approach find?")}

<h2>Precision by Test Case</h2>
{svg_bar(prec_data, title="Precision — of the results returned, how many were relevant?")}

<h2>Detailed Results</h2>
'''

    for r in results:
        e, b = r["enhanced"], r["baseline"]
        gt = r["ground_truth"]

        if r["winner"] == "enhanced":
            badge = '<span class="tag tag-win">ENHANCED WINS</span>'
        elif r["winner"] == "baseline":
            badge = '<span class="tag tag-loss">BASELINE WINS</span>'
        else:
            badge = '<span class="tag tag-tie">TIE</span>'

        e_found_set = set(e["found"])
        b_found_set = set(b["found"])
        gt_set = set(gt)

        html += f'''
<div class="card">
  <div class="card-head">
    <div class="q"><span class="tid">{r["id"]}</span>{r["question"]}</div>
    {badge}
  </div>
  <div class="cols">
    <div class="col enh">
      <div class="title">Enhanced (MCP Tools)</div>
      <div class="row"><span>Recall</span><span class="v">{e["recall"]}%</span></div>
      <div class="row"><span>Precision</span><span class="v">{e["precision"]}%</span></div>
      <div class="row"><span>Hits / Total</span><span class="v">{e["hits"]} / {e["total"]}</span></div>
      <div class="row"><span>Time</span><span class="v">{e["time_ms"]}ms</span></div>
      <div class="pills">'''

        for item in e["found"][:10]:
            cls = "pill hit" if item in gt_set else "pill"
            html += f'<span class="{cls}">{item}</span>'

        html += f'''</div>
    </div>
    <div class="col bas">
      <div class="title">Baseline (grep)</div>
      <div class="row"><span>Recall</span><span class="v">{b["recall"]}%</span></div>
      <div class="row"><span>Precision</span><span class="v">{b["precision"]}%</span></div>
      <div class="row"><span>Hits / Total</span><span class="v">{b["hits"]} / {b["total"]}</span></div>
      <div class="row"><span>Time</span><span class="v">{b["time_ms"]}ms</span></div>
      <div class="pills">'''

        for item in b["found"][:10]:
            cls = "pill hit" if item in gt_set else "pill"
            html += f'<span class="{cls}">{item}</span>'

        html += f'''</div>
    </div>
  </div>
  <div class="gt"><b>Ground truth:</b> {", ".join(gt)}</div>
</div>'''

    html += f'''
<div class="foot">Generated by Codebase Intelligence eval suite · {len(results)} tests · Sparrow project</div>
</div>
</body>
</html>'''
    return html


def main():
    results = load_results()
    html = generate_html(results)
    out = Path(__file__).parent / "eval_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"Report → {out}")
    os.startfile(str(out))


if __name__ == "__main__":
    main()
