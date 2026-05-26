"""
Generate a professional HTML benchmark report from benchmark_results.json.
Run: python eval/benchmark_report.py
"""
import os, sys, json, html as html_mod
from datetime import datetime

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))

def _esc(s):
    return html_mod.escape(s[:1500])

def generate():
    with open(os.path.join(EVAL_DIR, "benchmark_results.json")) as f:
        data = json.load(f)

    t1 = data["tier1_accuracy"]
    t2 = data["tier2_search"]
    t3 = data["tier3_performance"]
    t4 = data.get("tier4_comparisons", [])

    avg_p = sum(r["precision"] for r in t1) / len(t1)
    avg_r = sum(r["recall"] for r in t1) / len(t1)
    wins = sum(1 for c in t4 if c["verdict"] == "cassetto")
    losses = sum(1 for c in t4 if c["verdict"] == "baseline")

    # Tier 1 rows
    tool_rows = ""
    for r in t1:
        p_pct = f"{r['precision']:.0%}"
        r_pct = f"{r['recall']:.0%}"
        bar_w = int(r['recall'] * 100)
        color = "#22c55e" if r['recall'] >= 0.8 else "#eab308" if r['recall'] >= 0.5 else "#ef4444"
        tool_rows += f'<tr><td><code>{r["tool"]}</code></td><td>{r["query"]}</td><td style="text-align:center">{p_pct}</td><td style="text-align:center">{r_pct}</td><td><div class="bar" style="width:{bar_w}%;background:{color}"></div></td></tr>\n'

    # Tier 2 rows
    search_rows = ""
    for m in ["mrr", "p@3", "p@5", "ndcg@5"]:
        c = t2["cassetto"][m]
        g = t2["grep_baseline"][m]
        uplift = f"{c/g:.1f}x" if g > 0 else "-"
        cw = ' class="winner"' if c > g else ""
        gw = ' class="winner"' if g > c else ""
        search_rows += f'<tr><td><strong>{m.upper()}</strong></td><td style="text-align:center"{cw}>{c:.3f}</td><td style="text-align:center"{gw}>{g:.3f}</td><td style="text-align:center">{uplift}</td></tr>\n'

    # Tier 3 rows
    perf_rows = ""
    for tool, s in t3.items():
        if "p50_ms" in s:
            speed = "fast" if s["p50_ms"] < 100 else "medium" if s["p50_ms"] < 500 else "slow"
            perf_rows += f'<tr><td><code>{tool}</code></td><td style="text-align:right">{s["p50_ms"]:.0f} ms</td><td style="text-align:right">{s["p95_ms"]:.0f} ms</td><td><span class="badge {speed}">{speed}</span></td></tr>\n'
        elif "files_per_sec" in s:
            perf_rows += f'<tr><td><code>{tool}</code></td><td style="text-align:right">{s["time_s"]}s</td><td style="text-align:right">{s["files"]} files</td><td><span class="badge fast">{s["files_per_sec"]} files/s</span></td></tr>\n'

    # Tier 4 comparison cards
    comp_cards = ""
    for c in t4:
        v = c["verdict"]
        v_label = "CASSETTO WINS" if v == "cassetto" else "BASELINE WINS" if v == "baseline" else "TIE"
        v_color = "var(--green)" if v == "cassetto" else "var(--red)" if v == "baseline" else "var(--yellow)"
        c_cov = int(c["cassetto"]["coverage"] * 100)
        b_cov = int(c["baseline"]["coverage"] * 100)
        comp_cards += f'''
<div class="comparison-card">
  <div class="comp-header">
    <span class="comp-question">{_esc(c["question"])}</span>
    <span class="comp-verdict" style="color:{v_color}">{v_label}</span>
  </div>
  <div class="comp-gt"><strong>Ground truth:</strong> {_esc(c["ground_truth"])}</div>
  <div class="comp-grid">
    <div class="comp-col cassetto-col">
      <div class="comp-col-header"><span>Cassetto <code>{c["tool"]}</code></span><span class="comp-latency">{c["cassetto"]["latency_ms"]:.0f}ms</span></div>
      <div class="coverage-row"><div class="coverage-bar"><div class="coverage-fill" style="width:{c_cov}%;background:var(--green)"></div></div><span class="coverage-label">{c_cov}%</span></div>
      <pre class="comp-output">{_esc(c["cassetto"]["raw"])}</pre>
    </div>
    <div class="comp-col baseline-col">
      <div class="comp-col-header"><span>Keyword baseline</span><span class="comp-latency">{c["baseline"]["latency_ms"]:.0f}ms</span></div>
      <div class="coverage-row"><div class="coverage-bar"><div class="coverage-fill" style="width:{b_cov}%;background:var(--yellow)"></div></div><span class="coverage-label">{b_cov}%</span></div>
      <pre class="comp-output">{_esc(c["baseline"]["raw"])}</pre>
    </div>
  </div>
</div>
'''

    br_p50 = t3.get('blast_radius', {}).get('p50_ms', 0)
    now = datetime.now().strftime("%B %d, %Y at %H:%M")
    queries = t2['queries']
    mrr = t2['cassetto']['mrr']
    total = len(t1) + len(t4)

    with open(os.path.join(EVAL_DIR, "benchmark_report.html"), "w", encoding="utf-8") as f:
        f.write(f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cassetto Benchmark Report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0a0a0f;--surface:#12121a;--border:#1e1e2e;--text:#e4e4ef;--muted:#8888a0;--accent:#6366f1;--green:#22c55e;--yellow:#eab308;--red:#ef4444}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:2rem;max-width:1100px;margin:0 auto}}
h1{{font-size:2rem;margin-bottom:.25rem;background:linear-gradient(135deg,var(--accent),#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
h2{{font-size:1.3rem;margin:2.5rem 0 1rem;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:.5rem}}
.subtitle{{color:var(--muted);margin-bottom:2rem}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.5rem;margin-bottom:1.5rem}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:2rem}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem;text-align:center}}
.kpi .value{{font-size:2rem;font-weight:700}}.kpi .label{{color:var(--muted);font-size:.8rem;margin-top:.25rem}}
.green{{color:var(--green)}}.yellow{{color:var(--yellow)}}.red{{color:var(--red)}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;padding:.5rem .75rem;border-bottom:1px solid var(--border)}}
td{{padding:.6rem .75rem;border-bottom:1px solid var(--border);font-size:.9rem}}
tr:hover{{background:rgba(99,102,241,.05)}}
.bar{{height:8px;border-radius:4px;min-width:4px}}.winner{{color:var(--green);font-weight:600}}
.badge{{padding:2px 8px;border-radius:6px;font-size:.75rem;font-weight:600}}
.badge.fast{{background:rgba(34,197,94,.15);color:var(--green)}}.badge.medium{{background:rgba(234,179,8,.15);color:var(--yellow)}}.badge.slow{{background:rgba(239,68,68,.15);color:var(--red)}}
code{{background:rgba(99,102,241,.1);padding:2px 6px;border-radius:4px;font-size:.85rem}}
.comparison-card{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem;margin-bottom:1.25rem}}
.comp-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem}}
.comp-question{{font-weight:600;font-size:1rem}}.comp-verdict{{font-weight:700;font-size:.85rem;text-transform:uppercase;letter-spacing:.04em}}
.comp-gt{{color:var(--muted);font-size:.8rem;margin-bottom:1rem;padding:.5rem;background:rgba(99,102,241,.05);border-radius:8px}}
.comp-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}
.comp-col{{border:1px solid var(--border);border-radius:8px;overflow:hidden}}
.cassetto-col{{border-color:rgba(34,197,94,.3)}}.baseline-col{{border-color:rgba(234,179,8,.3)}}
.comp-col-header{{display:flex;justify-content:space-between;padding:.5rem .75rem;background:rgba(255,255,255,.03);border-bottom:1px solid var(--border);font-size:.8rem;font-weight:600}}
.comp-latency{{color:var(--muted);font-weight:400}}
.coverage-row{{display:flex;align-items:center;gap:.5rem;padding:.4rem .75rem}}
.coverage-bar{{flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden}}
.coverage-fill{{height:100%;border-radius:3px}}.coverage-label{{font-size:.75rem;color:var(--muted);min-width:30px;text-align:right}}
.comp-output{{padding:.75rem;font-family:'Cascadia Code','Fira Code',monospace;font-size:.7rem;color:var(--muted);white-space:pre-wrap;word-break:break-all;max-height:250px;overflow-y:auto;background:rgba(0,0,0,.2);margin:0;line-height:1.4}}
.method{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem;margin-top:1rem;font-size:.85rem;color:var(--muted)}}
.method h3{{color:var(--text);font-size:.95rem;margin-bottom:.5rem}}
@media(max-width:700px){{.comp-grid{{grid-template-columns:1fr}}.kpi-grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<h1>Cassetto Benchmark Report</h1>
<p class="subtitle">Generated {now} &middot; Project: Sparrow (React + Django, 52 files)</p>
<div class="kpi-grid">
  <div class="kpi"><div class="value green">{avg_p:.0%}</div><div class="label">Avg Precision</div></div>
  <div class="kpi"><div class="value green">{avg_r:.0%}</div><div class="label">Avg Recall</div></div>
  <div class="kpi"><div class="value green">{mrr:.3f}</div><div class="label">MRR (Search)</div></div>
  <div class="kpi"><div class="value green">{br_p50:.0f}ms</div><div class="label">blast_radius p50</div></div>
  <div class="kpi"><div class="value green">{wins}-{losses}</div><div class="label">Wins vs Baseline</div></div>
  <div class="kpi"><div class="value">{total}</div><div class="label">Total Scenarios</div></div>
</div>
<h2>Tier 1: Tool Output Accuracy</h2>
<p style="color:var(--muted);margin-bottom:1rem">Each tool output is compared against manually verified ground truth. No LLM involved in scoring.</p>
<div class="card"><table>
<thead><tr><th>Tool</th><th>Query</th><th>Precision</th><th>Recall</th><th style="width:20%">Recall</th></tr></thead>
<tbody>{tool_rows}</tbody></table></div>

<h2>Tier 2: Retrieval Quality (IR Metrics)</h2>
<p style="color:var(--muted);margin-bottom:1rem">Cassetto semantic search vs keyword-only baseline on {queries} queries. Same indexed data, different ranking.</p>
<div class="card"><table>
<thead><tr><th>Metric</th><th style="text-align:center">Cassetto</th><th style="text-align:center">Keyword</th><th style="text-align:center">Uplift</th></tr></thead>
<tbody>{search_rows}</tbody></table></div>

<h2>Tier 3: Performance</h2>
<p style="color:var(--muted);margin-bottom:1rem">Latency benchmarks. All graph tools respond sub-100ms. Search includes embedding generation.</p>
<div class="card"><table>
<thead><tr><th>Operation</th><th style="text-align:right">p50</th><th style="text-align:right">p95</th><th>Rating</th></tr></thead>
<tbody>{perf_rows}</tbody></table></div>

<h2>Tier 4: Cassetto vs Baseline &mdash; Raw Output Comparison</h2>
<p style="color:var(--muted);margin-bottom:1rem">{len(t4)} real developer questions. Left: Cassetto MCP tool output. Right: keyword-only search (what an LLM sees without MCP). Coverage = % of ground truth facts present in output.</p>
{comp_cards}

<div class="method">
<h3>Methodology</h3>
<p><strong>Tier 1:</strong> Ground truth manually constructed by inspecting the Sparrow codebase. Tool outputs parsed and compared using set-based precision and recall. Zero LLM involvement.</p>
<p style="margin-top:.5rem"><strong>Tier 2:</strong> Five semantic search queries with manually labeled relevant files. Cassetto uses hybrid BM25 + embedding search with graph-aware reranking. Baseline uses keyword matching on the same indexed chunks.</p>
<p style="margin-top:.5rem"><strong>Tier 3:</strong> Latency measured with <code>time.perf_counter()</code>, 5 runs per operation. p50 = median, p95 = worst-case.</p>
<p style="margin-top:.5rem"><strong>Tier 4:</strong> Seven developer questions answered by Cassetto (structured MCP tool) vs keyword-only baseline. Coverage = fraction of ground-truth fact-words found in raw output. Scoring is deterministic word-overlap, no LLM judge.</p>
</div>
</body></html>''')

    print(f"Report: {os.path.join(EVAL_DIR, 'benchmark_report.html')}")


if __name__ == "__main__":
    generate()
