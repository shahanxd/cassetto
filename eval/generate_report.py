"""Generate a professional HTML evaluation report from LLM eval results."""
import os, sys, json

_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

with open(os.path.join(os.path.dirname(__file__), 'llm_eval_results.json'), encoding='utf-8') as f:
    results = json.load(f)

c_wins = sum(1 for r in results if r['winner'] == 'cassetto')
v_wins = sum(1 for r in results if r['winner'] == 'vanilla')
ties = sum(1 for r in results if r['winner'] == 'tie')
c_acc = sum(r['cassetto']['accuracy'] for r in results) / len(results)
v_acc = sum(r['vanilla']['accuracy'] for r in results) / len(results)
c_spec = sum(r['cassetto']['specificity'] for r in results) / len(results)
v_spec = sum(r['vanilla']['specificity'] for r in results) / len(results)

# Build test rows
test_rows = ""
for r in results:
    va = r['vanilla']['accuracy']
    ca = r['cassetto']['accuracy']
    vs = r['vanilla']['specificity']
    cs = r['cassetto']['specificity']
    w = r['winner']
    badge = '🟢 Cassetto' if w == 'cassetto' else ('🔴 Vanilla' if w == 'vanilla' else '⚪ Tie')

    # escape HTML in answers
    import html
    van_answer = html.escape(r['vanilla']['answer'][:600])
    cas_answer = html.escape(r['cassetto']['answer'][:600])

    test_rows += f"""
    <div class="test-card">
      <div class="test-header">
        <span class="test-id">{r['id']}</span>
        <span class="test-question">{html.escape(r['question'])}</span>
        <span class="badge {'win' if w=='cassetto' else 'loss' if w=='vanilla' else 'tie'}">{badge}</span>
      </div>
      <div class="scores-row">
        <div class="score-box vanilla-box">
          <div class="score-label">LLM + Project Files</div>
          <div class="score-metrics">
            <span>Accuracy: <strong>{va:.0f}%</strong></span>
            <span>Specificity: <strong>{vs:.0f}%</strong></span>
          </div>
          <div class="answer-preview">{van_answer}</div>
        </div>
        <div class="score-box cassetto-box">
          <div class="score-label">LLM + Cassetto</div>
          <div class="score-metrics">
            <span>Accuracy: <strong>{ca:.0f}%</strong></span>
            <span>Specificity: <strong>{cs:.0f}%</strong></span>
          </div>
          <div class="answer-preview">{cas_answer}</div>
        </div>
      </div>
    </div>
    """

report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cassetto — LLM Code Intelligence Evaluation Report</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --text-muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --cassetto: #238636; --vanilla: #6e7681;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
    padding: 0; min-height: 100vh;
  }}
  .hero {{
    background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #1a2332 100%);
    border-bottom: 1px solid var(--border);
    padding: 60px 40px 50px;
    text-align: center;
  }}
  .hero h1 {{
    font-size: 2.8rem; font-weight: 800;
    background: linear-gradient(135deg, #58a6ff, #3fb950);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }}
  .hero .subtitle {{ color: var(--text-muted); font-size: 1.1rem; }}
  .hero .methodology {{
    margin-top: 20px; padding: 16px 24px; background: rgba(88,166,255,0.08);
    border: 1px solid rgba(88,166,255,0.2); border-radius: 8px;
    display: inline-block; text-align: left; max-width: 700px;
    font-size: 0.9rem; color: var(--text-muted);
  }}
  .hero .methodology strong {{ color: var(--text); }}

  .container {{ max-width: 1200px; margin: 0 auto; padding: 40px 24px; }}

  /* ── Summary Cards ── */
  .summary-grid {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
    margin-bottom: 40px;
  }}
  .stat-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px; text-align: center;
  }}
  .stat-card .number {{
    font-size: 2.8rem; font-weight: 800; line-height: 1;
  }}
  .stat-card .label {{
    font-size: 0.85rem; color: var(--text-muted); margin-top: 4px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }}
  .stat-card.green .number {{ color: var(--green); }}
  .stat-card.red .number {{ color: var(--red); }}
  .stat-card.blue .number {{ color: var(--accent); }}

  /* ── Bar Comparison ── */
  .comparison-section {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 32px; margin-bottom: 40px;
  }}
  .comparison-section h2 {{ font-size: 1.4rem; margin-bottom: 24px; }}
  .bar-row {{
    display: flex; align-items: center; margin-bottom: 16px; gap: 12px;
  }}
  .bar-label {{ width: 100px; font-size: 0.85rem; color: var(--text-muted); text-align: right; }}
  .bar-track {{
    flex: 1; height: 32px; background: rgba(255,255,255,0.05);
    border-radius: 6px; overflow: hidden; position: relative;
  }}
  .bar-fill {{
    height: 100%; border-radius: 6px; display: flex;
    align-items: center; padding: 0 12px;
    font-size: 0.85rem; font-weight: 600; min-width: 40px;
    transition: width 1s ease;
  }}
  .bar-fill.cassetto {{ background: var(--green); }}
  .bar-fill.vanilla {{ background: var(--vanilla); }}

  /* ── Test Cards ── */
  .tests-section h2 {{ font-size: 1.4rem; margin-bottom: 20px; }}
  .test-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; margin-bottom: 16px; overflow: hidden;
  }}
  .test-header {{
    display: flex; align-items: center; gap: 12px;
    padding: 16px 20px; border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }}
  .test-id {{
    background: var(--accent); color: #000; font-weight: 700;
    padding: 2px 10px; border-radius: 4px; font-size: 0.85rem;
  }}
  .test-question {{ flex: 1; font-size: 0.95rem; min-width: 200px; }}
  .badge {{
    padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600;
  }}
  .badge.win {{ background: rgba(63,185,80,0.15); color: var(--green); }}
  .badge.loss {{ background: rgba(248,81,73,0.15); color: var(--red); }}
  .badge.tie {{ background: rgba(139,148,158,0.15); color: var(--text-muted); }}

  .scores-row {{ display: grid; grid-template-columns: 1fr 1fr; }}
  .score-box {{ padding: 16px 20px; }}
  .score-box.vanilla-box {{ border-right: 1px solid var(--border); }}
  .score-label {{
    font-size: 0.8rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.05em; margin-bottom: 8px;
  }}
  .vanilla-box .score-label {{ color: var(--vanilla); }}
  .cassetto-box .score-label {{ color: var(--green); }}
  .score-metrics {{
    display: flex; gap: 20px; margin-bottom: 12px; font-size: 0.9rem;
  }}
  .score-metrics strong {{ color: var(--text); }}
  .answer-preview {{
    font-size: 0.8rem; color: var(--text-muted);
    background: rgba(0,0,0,0.3); padding: 12px; border-radius: 6px;
    max-height: 200px; overflow-y: auto; white-space: pre-wrap;
    word-wrap: break-word; line-height: 1.5;
  }}

  /* ── Footer ── */
  .footer {{
    text-align: center; padding: 40px; color: var(--text-muted);
    font-size: 0.85rem; border-top: 1px solid var(--border);
  }}

  @media (max-width: 768px) {{
    .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .scores-row {{ grid-template-columns: 1fr; }}
    .score-box.vanilla-box {{ border-right: none; border-bottom: 1px solid var(--border); }}
    .hero h1 {{ font-size: 2rem; }}
  }}
</style>
</head>
<body>

<div class="hero">
  <h1>Cassetto Evaluation Report</h1>
  <p class="subtitle">Real-World LLM Code Intelligence — Side-by-Side Comparison</p>
  <div class="methodology">
    <strong>Methodology:</strong> 10 natural developer questions were sent to the same LLM (Llama 3.2 3B) under two conditions:<br>
    <strong>Vanilla:</strong> LLM receives all project source files in its context window (~20K tokens) — simulating a standard IDE AI assistant.<br>
    <strong>Cassetto:</strong> LLM receives structured Cassetto tool outputs (call graphs, blast radius, imports, git churn, architecture analysis).<br>
    Both answers were scored against manually verified ground truth.<br>
    <strong>Accuracy</strong> = did the answer contain the required facts?&emsp;
    <strong>Specificity</strong> = did it name exact functions, files, and line numbers?
  </div>
</div>

<div class="container">

  <!-- Summary Stats -->
  <div class="summary-grid">
    <div class="stat-card green">
      <div class="number">{c_wins}–{v_wins}</div>
      <div class="label">Cassetto Wins</div>
    </div>
    <div class="stat-card blue">
      <div class="number">{c_acc:.0f}%</div>
      <div class="label">Cassetto Accuracy</div>
    </div>
    <div class="stat-card red">
      <div class="number">{v_acc:.0f}%</div>
      <div class="label">Vanilla Accuracy</div>
    </div>
    <div class="stat-card green">
      <div class="number">{c_acc/v_acc:.1f}×</div>
      <div class="label">Accuracy Uplift</div>
    </div>
  </div>

  <!-- Bar Comparison -->
  <div class="comparison-section">
    <h2>Head-to-Head Comparison</h2>

    <div class="bar-row">
      <div class="bar-label">Accuracy</div>
      <div class="bar-track">
        <div class="bar-fill cassetto" style="width: {c_acc}%">{c_acc:.0f}%</div>
      </div>
    </div>
    <div class="bar-row">
      <div class="bar-label"></div>
      <div class="bar-track">
        <div class="bar-fill vanilla" style="width: {max(v_acc, 5)}%">{v_acc:.0f}%</div>
      </div>
    </div>

    <div style="height: 16px"></div>

    <div class="bar-row">
      <div class="bar-label">Specificity</div>
      <div class="bar-track">
        <div class="bar-fill cassetto" style="width: {c_spec}%">{c_spec:.0f}%</div>
      </div>
    </div>
    <div class="bar-row">
      <div class="bar-label"></div>
      <div class="bar-track">
        <div class="bar-fill vanilla" style="width: {max(v_spec, 5)}%">{v_spec:.0f}%</div>
      </div>
    </div>

    <div style="margin-top: 12px; display: flex; gap: 20px; font-size: 0.85rem; color: var(--text-muted);">
      <span><span style="color: var(--green);">■</span> LLM + Cassetto</span>
      <span><span style="color: var(--vanilla);">■</span> Vanilla LLM</span>
    </div>
  </div>

  <!-- Per-test results -->
  <div class="tests-section">
    <h2>Detailed Results — All 10 Questions</h2>
    {test_rows}
  </div>

</div>

<div class="footer">
  Cassetto — Local-first code intelligence for LLMs<br>
  Evaluation run with Llama 3.2 3B on Sparrow codebase (52 files, React + Django)
</div>

</body>
</html>"""

out_path = os.path.join(os.path.dirname(__file__), 'eval_report.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(report_html)
print(f"Report -> {out_path}")
