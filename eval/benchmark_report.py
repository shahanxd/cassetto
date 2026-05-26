"""
Generate a professional HTML benchmark report from benchmark_results.json.
Run: python eval/benchmark_report.py
"""
import os, sys, json
from datetime import datetime

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))

def generate():
    with open(os.path.join(EVAL_DIR, "benchmark_results.json")) as f:
        data = json.load(f)

    t1 = data["tier1_accuracy"]
    t2 = data["tier2_search"]
    t3 = data["tier3_performance"]

    avg_p = sum(r["precision"] for r in t1) / len(t1)
    avg_r = sum(r["recall"] for r in t1) / len(t1)

    # Build tool accuracy rows
    tool_rows = ""
    for r in t1:
        p_pct = f"{r['precision']:.0%}"
        r_pct = f"{r['recall']:.0%}"
        bar_w = int(r['recall'] * 100)
        color = "#22c55e" if r['recall'] >= 0.8 else "#eab308" if r['recall'] >= 0.5 else "#ef4444"
        tool_rows += f"""
        <tr>
          <td><code>{r['tool']}</code></td>
          <td>{r['query']}</td>
          <td style="text-align:center">{p_pct}</td>
          <td style="text-align:center">{r_pct}</td>
          <td><div class="bar" style="width:{bar_w}%;background:{color}"></div></td>
        </tr>"""

    # Search quality rows
    search_rows = ""
    for m in ["mrr", "p@3", "p@5", "ndcg@5"]:
        c = t2["cassetto"][m]
        g = t2["grep_baseline"][m]
        uplift = f"{c/g:.1f}x" if g > 0 else "-"
        winner = "cassetto" if c > g else "grep" if g > c else "tie"
        search_rows += f"""
        <tr>
          <td><strong>{m.upper()}</strong></td>
          <td style="text-align:center" class="{'winner' if winner=='cassetto' else ''}">{c:.3f}</td>
          <td style="text-align:center" class="{'winner' if winner=='grep' else ''}">{g:.3f}</td>
          <td style="text-align:center">{uplift}</td>
        </tr>"""

    # Performance rows
    perf_rows = ""
    for tool, s in t3.items():
        if "p50_ms" in s:
            speed = "fast" if s["p50_ms"] < 100 else "medium" if s["p50_ms"] < 500 else "slow"
            perf_rows += f"""
            <tr>
              <td><code>{tool}</code></td>
              <td style="text-align:right">{s['p50_ms']:.0f} ms</td>
              <td style="text-align:right">{s['p95_ms']:.0f} ms</td>
              <td><span class="badge {speed}">{speed}</span></td>
            </tr>"""
        elif "files_per_sec" in s:
            perf_rows += f"""
            <tr>
              <td><code>{tool}</code></td>
              <td style="text-align:right">{s['time_s']}s</td>
              <td style="text-align:right">{s['files']} files</td>
              <td><span class="badge fast">{s['files_per_sec']} files/s</span></td>
            </tr>"""

    br_p50 = t3.get('blast_radius', {}).get('p50_ms', 0)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cassetto Benchmark Report</title>
<style>
  :root {{ --bg: #0a0a0f; --surface: #12121a; --border: #1e1e2e; --text: #e4e4ef;
           --muted: #8888a0; --accent: #6366f1; --green: #22c55e; --yellow: #eab308; --red: #ef4444; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text);
          line-height: 1.6; padding: 2rem; max-width: 1000px; margin: 0 auto; }}
  h1 {{ font-size: 2rem; margin-bottom: 0.25rem; background: linear-gradient(135deg, var(--accent), #a78bfa);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  h2 {{ font-size: 1.3rem; margin: 2.5rem 0 1rem; color: var(--accent); border-bottom: 1px solid var(--border);
        padding-bottom: 0.5rem; }}
  .subtitle {{ color: var(--muted); margin-bottom: 2rem; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
           padding: 1.5rem; margin-bottom: 1.5rem; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
          padding: 1.25rem; text-align: center; }}
  .kpi .value {{ font-size: 2rem; font-weight: 700; }}
  .kpi .label {{ color: var(--muted); font-size: 0.85rem; margin-top: 0.25rem; }}
  .green {{ color: var(--green); }} .yellow {{ color: var(--yellow); }} .red {{ color: var(--red); }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; color: var(--muted); font-size: 0.8rem; text-transform: uppercase;
       letter-spacing: 0.05em; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }}
  td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
  tr:hover {{ background: rgba(99, 102, 241, 0.05); }}
  .bar {{ height: 8px; border-radius: 4px; min-width: 4px; }}
  .winner {{ color: var(--green); font-weight: 600; }}
  .badge {{ padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }}
  .badge.fast {{ background: rgba(34,197,94,0.15); color: var(--green); }}
  .badge.medium {{ background: rgba(234,179,8,0.15); color: var(--yellow); }}
  .badge.slow {{ background: rgba(239,68,68,0.15); color: var(--red); }}
  .method {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
             padding: 1.25rem; margin-top: 1rem; font-size: 0.85rem; color: var(--muted); }}
  .method h3 {{ color: var(--text); font-size: 0.95rem; margin-bottom: 0.5rem; }}
  code {{ background: rgba(99,102,241,0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }}
  @media (max-width: 600px) {{ .kpi-grid {{ grid-template-columns: 1fr 1fr; }} }}
</style>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body>
<h1>Cassetto Benchmark Report</h1>
<p class="subtitle">Generated {datetime.now().strftime("%B %d, %Y at %H:%M")} &middot; Project: Sparrow (React + Django, 52 files)</p>

<div class="kpi-grid">
  <div class="kpi"><div class="value green">{avg_p:.0%}</div><div class="label">Avg Precision</div></div>
  <div class="kpi"><div class="value green">{avg_r:.0%}</div><div class="label">Avg Recall</div></div>
  <div class="kpi"><div class="value green">{t2['cassetto']['mrr']:.3f}</div><div class="label">MRR (Search)</div></div>
  <div class="kpi"><div class="value green">{br_p50:.0f}ms</div><div class="label">blast_radius p50</div></div>
  <div class="kpi"><div class="value">{len(t1)}</div><div class="label">Tools Tested</div></div>
</div>

<h2>Tier 1: Tool Output Accuracy</h2>
<p style="color:var(--muted);margin-bottom:1rem">Each tool output is compared against manually verified ground truth. No LLM involved in scoring.</p>
<div class="card">
<table>
  <thead><tr><th>Tool</th><th>Query</th><th>Precision</th><th>Recall</th><th style="width:20%">Recall</th></tr></thead>
  <tbody>{tool_rows}</tbody>
</table>
</div>

<h2>Tier 2: Retrieval Quality (IR Metrics)</h2>
<p style="color:var(--muted);margin-bottom:1rem">Cassetto semantic search vs keyword-only baseline on {t2['queries']} queries. Same indexed data, different ranking.</p>
<div class="card">
<table>
  <thead><tr><th>Metric</th><th style="text-align:center">Cassetto</th><th style="text-align:center">Keyword</th><th style="text-align:center">Uplift</th></tr></thead>
  <tbody>{search_rows}</tbody>
</table>
</div>

<h2>Tier 3: Performance</h2>
<p style="color:var(--muted);margin-bottom:1rem">Latency benchmarks. All graph tools respond sub-100ms. Search includes embedding generation.</p>
<div class="card">
<table>
  <thead><tr><th>Operation</th><th style="text-align:right">p50</th><th style="text-align:right">p95</th><th>Rating</th></tr></thead>
  <tbody>{perf_rows}</tbody>
</table>
</div>

<div class="method">
  <h3>Methodology</h3>
  <p><strong>Tier 1:</strong> Ground truth was manually constructed by inspecting the Sparrow codebase (React + Django AQI dashboard, 52 files).
  Each tool's output is parsed and compared against known-correct facts using set-based precision and recall. Zero LLM involvement in scoring.</p>
  <p style="margin-top:0.5rem"><strong>Tier 2:</strong> Five semantic search queries with manually labeled relevant files.
  Cassetto uses hybrid BM25 + embedding search with graph-aware reranking. Baseline uses keyword matching on the same indexed chunks.
  Metrics: MRR (Mean Reciprocal Rank), Precision@K, nDCG@5.</p>
  <p style="margin-top:0.5rem"><strong>Tier 3:</strong> Latency measured with <code>time.perf_counter()</code>, 5 runs per operation.
  p50 = median, p95 = worst-case. Index throughput includes parsing, embedding, graph construction, and git analysis.</p>
</div>

</body></html>"""

    out = os.path.join(EVAL_DIR, "benchmark_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report: {out}")


if __name__ == "__main__":
    generate()
