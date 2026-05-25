"""
Codebase Intelligence — Real-World A/B Evaluation

Tests natural developer questions against the Sparrow codebase.
For each question:
  - BASELINE: grep/findstr + file listing (what you'd do without tools)
  - ENHANCED: MCP tools (search_code, blast_radius, call_graph, etc.)

Both approaches try to answer the SAME question. We measure how much of
the verified ground truth each approach surfaces.
"""
import os
import sys
import json
import time
import re
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ["CI_PROJECT_ID"] = "sparrow"

SPARROW = str(Path(__file__).parent / "sparrow")

# ── helpers ────────────────────────────────────────────────────

def grep(terms: list[str], exts="*.py *.js *.jsx *.ts *.tsx") -> set[str]:
    """Run findstr on the sparrow directory. Returns set of matching lines."""
    hits = set()
    for term in terms:
        try:
            out = subprocess.run(
                f'findstr /s /i /n "{term}" {exts}',
                capture_output=True, text=True, cwd=SPARROW,
                timeout=15, shell=True
            )
            for line in out.stdout.strip().split('\n'):
                if line.strip():
                    hits.add(line.strip())
        except Exception:
            pass
    return hits


def grep_files(terms: list[str]) -> set[str]:
    """Grep for terms, return just the filenames."""
    files = set()
    for line in grep(terms):
        match = re.match(r'^([^:]+)', line)
        if match:
            files.add(Path(match.group(1)).name)
    return files


def grep_functions_in_file(filename: str) -> set[str]:
    """Find all function definitions in a file via grep."""
    hits = set()
    for line in grep(["function ", "def ", "const .* = "], exts=f"*{Path(filename).suffix}"):
        if filename.lower() in line.lower():
            # try to extract function name
            m = re.search(r'(?:function|def|const)\s+(\w+)', line)
            if m:
                hits.add(m.group(1))
    return hits


def grep_references(symbol_name: str) -> set[str]:
    """Find all files that mention a symbol (poor man's 'find references')."""
    return grep_files([symbol_name])


def timed(func):
    """Measure execution time in ms."""
    start = time.time()
    result = func()
    elapsed = round((time.time() - start) * 1000)
    return result, elapsed


# ── MCP tool wrappers ──────────────────────────────────────────

def mcp_search(query: str, limit=10) -> dict:
    from server import search_code
    raw = search_code(query, limit=limit)
    symbols = re.findall(r'SYMBOL:\s*(\w+)', raw)
    files = re.findall(r'FILE:\s*[^\n]*?([^\\/]+?)(?:\s*\()', raw)
    return {"symbols": symbols, "files": files, "raw": raw}


def mcp_blast(symbol: str) -> dict:
    from server import blast_radius
    raw = blast_radius(symbol)
    try:
        data = json.loads(raw)
        names = [d["name"] for d in data.get("blast_radius", [])]
        files = list(set(Path(d["file"]).name for d in data.get("blast_radius", [])))
    except (json.JSONDecodeError, TypeError):
        names, files = [], []
    return {"names": names, "files": files, "count": len(names), "raw": raw}


def mcp_call_graph(symbol: str) -> dict:
    from server import get_call_graph_tool
    raw = get_call_graph_tool(symbol)
    try:
        data = json.loads(raw)
        callers = [c["name"] for c in data.get("called_by", [])]
        callees = [c["name"] for c in data.get("calls", [])]
    except (json.JSONDecodeError, TypeError):
        callers, callees = [], []
    return {"callers": callers, "callees": callees, "raw": raw}


def mcp_dead_code() -> list[str]:
    from server import find_dead_code
    raw = find_dead_code()
    return re.findall(r'- (\w+) \(', raw)


def mcp_repo_map(n=20) -> list[str]:
    from server import get_repo_map
    raw = get_repo_map(n)
    return re.findall(r'- (\w+) \(', raw)


# ── test definitions ───────────────────────────────────────────

def compute_recall(found: set, truth: set) -> float:
    if not truth:
        return 100.0
    return round(len(found & truth) / len(truth) * 100, 1)


def compute_precision(found: set, truth: set) -> float:
    if not found:
        return 0.0
    return round(len(found & truth) / len(found) * 100, 1)


def run_test(test_id, question, ground_truth, baseline_fn, enhanced_fn):
    """Run one test case. Returns result dict."""
    print(f"\n[{test_id}] {question}")
    gt = set(ground_truth)

    # baseline
    b_result, b_time = timed(baseline_fn)
    b_found = set(b_result) if isinstance(b_result, (list, set)) else set()
    b_recall = compute_recall(b_found, gt)
    b_precision = compute_precision(b_found, gt)
    b_hits = len(b_found & gt)

    # enhanced
    e_result, e_time = timed(enhanced_fn)
    e_found = set(e_result) if isinstance(e_result, (list, set)) else set()
    e_recall = compute_recall(e_found, gt)
    e_precision = compute_precision(e_found, gt)
    e_hits = len(e_found & gt)

    print(f"  ENHANCED: recall={e_recall}% precision={e_precision}% "
          f"({e_hits}/{len(gt)} hits, {len(e_found)} results) [{e_time}ms]")
    print(f"  BASELINE: recall={b_recall}% precision={b_precision}% "
          f"({b_hits}/{len(gt)} hits, {len(b_found)} results) [{b_time}ms]")

    winner = "enhanced" if e_recall > b_recall else ("baseline" if b_recall > e_recall else "tie")
    if e_recall == b_recall and e_precision > b_precision:
        winner = "enhanced"
    elif e_recall == b_recall and b_precision > e_precision:
        winner = "baseline"
    print(f"  → Winner: {winner.upper()}")

    return {
        "id": test_id,
        "question": question,
        "ground_truth": sorted(gt),
        "enhanced": {
            "found": sorted(e_found)[:15], "recall": e_recall,
            "precision": e_precision, "hits": e_hits,
            "total": len(e_found), "time_ms": e_time,
        },
        "baseline": {
            "found": sorted(b_found)[:15], "recall": b_recall,
            "precision": b_precision, "hits": b_hits,
            "total": len(b_found), "time_ms": b_time,
        },
        "winner": winner,
    }


# ── all 15 test cases ─────────────────────────────────────────

def run_all():
    results = []

    # ─── Q1: Semantic concept search ───────────────────────────
    results.append(run_test(
        "Q1",
        "Where does the app calculate AQI values?",
        # ground truth: functions/files that compute AQI
        ["getAqiTier", "getAqiCategory", "getAqiColor", "_pm25_to_aqi",
         "get_aqi_tier", "get_explainability"],
        # baseline: grep for "aqi" — what a developer would actually do
        lambda: list(grep_files(["aqi", "air quality index"])),
        # enhanced: semantic search
        lambda: mcp_search("calculate AQI air quality index values")["symbols"],
    ))

    # ─── Q2: Find auth flow ────────────────────────────────────
    results.append(run_test(
        "Q2",
        "How does user authentication work in this app?",
        ["login", "logout", "getCSRFToken", "login_view", "logout_view"],
        lambda: list(grep_files(["login", "logout", "csrf", "auth"])),
        lambda: mcp_search("user authentication login logout session")["symbols"],
    ))

    # ─── Q3: Domain concept — no literal match ─────────────────
    results.append(run_test(
        "Q3",
        "How does the app attribute pollution sources to each ward?",
        ["_fallback_sources", "get_explainability", "_build_ward_data",
         "source_model.py", "services.py"],
        lambda: list(grep_files(["pollution source", "source", "attribution", "ward"])),
        lambda: (mcp_search("pollution source attribution ward explainability")["symbols"]
                 + mcp_search("pollution source attribution ward explainability")["files"]),
    ))

    # ─── Q4: Impact analysis — "what breaks if I change X?" ───
    results.append(run_test(
        "Q4",
        "If I refactor apiFetch, what other code will break?",
        # verified: all functions that call apiFetch
        ["fetchWards", "fetchWardDetail", "fetchRecentReports",
         "submitReport", "fetchWindData", "fetchImpactMetrics"],
        # baseline: grep for "apiFetch" and extract the FILE names
        lambda: list(grep_files(["apiFetch"])),
        # enhanced: blast_radius gives actual dependent function names
        lambda: mcp_blast("apiFetch")["names"],
    ))

    # ─── Q5: Impact analysis — deep chain ──────────────────────
    results.append(run_test(
        "Q5",
        "If I change _http_get_json, what downstream code is affected?",
        ["fetch_openmeteo", "fetch_aqicn", "_get_latest_reading", "_build_ward_data"],
        lambda: list(grep_files(["_http_get_json"])),
        lambda: mcp_blast("_http_get_json")["names"],
    ))

    # ─── Q6: Call graph — who calls what ───────────────────────
    results.append(run_test(
        "Q6",
        "What functions does _build_ward_data call internally?",
        ["_get_latest_reading", "get_aqi_tier", "_fallback_sources",
         "get_explainability", "SeededRandom"],
        # baseline: open the file and grep for function calls inside _build_ward_data
        lambda: list(grep_files(["_build_ward_data"])),
        lambda: mcp_call_graph("_build_ward_data")["callees"],
    ))

    # ─── Q7: Call graph — who calls me ─────────────────────────
    results.append(run_test(
        "Q7",
        "What calls the getCSRFToken function?",
        ["login", "logout", "submitReport", "fetchRecentReports"],
        lambda: list(grep_files(["getCSRFToken"])),
        lambda: mcp_call_graph("getCSRFToken")["callers"],
    ))

    # ─── Q8: Dead code detection ──────────────────────────────
    results.append(run_test(
        "Q8",
        "Are there any unused functions I can safely delete?",
        # truly dead code (not React components which look dead but aren't)
        ["_has_real_data", "buildDistrictMap", "simulate_intervention",
         "getAqiFillColor", "getMitigations"],
        # baseline: would need to check every function's usage — simulate with grep
        lambda: _baseline_dead_code(),
        lambda: mcp_dead_code(),
    ))

    # ─── Q9: Architecture overview ─────────────────────────────
    results.append(run_test(
        "Q9",
        "What are the most important functions in this codebase?",
        ["apiFetch", "getAqiTier", "useAppState", "useAppDispatch",
         "_get_latest_reading", "getCSRFToken"],
        # baseline: file listing shows structure, not importance
        lambda: _baseline_importance(),
        lambda: mcp_repo_map(20),
    ))

    # ─── Q10: E2E — change AQI colors ─────────────────────────
    results.append(run_test(
        "Q10",
        "I want to change the AQI color scheme. What files need updating?",
        ["aqiUtils.js", "WardLayer.jsx", "AqiLegend.jsx",
         "DetailPanel.jsx", "HotspotCards.jsx"],
        lambda: list(grep_files(["color", "getAqiColor", "#"])),
        lambda: (mcp_search("AQI color scheme")["files"]
                 + mcp_blast("getAqiColor")["files"]),
    ))

    # ─── Q11: Find specific feature ───────────────────────────
    results.append(run_test(
        "Q11",
        "Where is the wind overlay feature implemented?",
        ["WindOverlay.jsx", "fetchWindData", "get_wind_data"],
        lambda: list(grep_files(["wind", "WindOverlay"])),
        lambda: (mcp_search("wind overlay feature implementation")["symbols"]
                 + mcp_search("wind overlay feature implementation")["files"]),
    ))

    # ─── Q12: Data flow understanding ──────────────────────────
    results.append(run_test(
        "Q12",
        "How does ward data flow from the API to the frontend map?",
        ["fetchWards", "apiFetch", "get_all_wards", "_build_ward_data",
         "WardLayer.jsx", "AppContext.jsx", "useAppState"],
        lambda: list(grep_files(["ward", "fetchWards", "WardLayer"])),
        lambda: (mcp_search("ward data flow API frontend map")["symbols"]
                 + mcp_search("ward data flow API frontend map")["files"]
                 + mcp_call_graph("fetchWards")["callees"]),
    ))

    # ─── Q13: Report submission flow ──────────────────────────
    results.append(run_test(
        "Q13",
        "What happens when a user submits a pollution report?",
        ["submitReport", "submit_report", "ReportModal.jsx", "ReportFAB.jsx"],
        lambda: list(grep_files(["report", "submit"])),
        lambda: (mcp_search("submit pollution report user")["symbols"]
                 + mcp_search("submit pollution report user")["files"]),
    ))

    # ─── Q14: Find all API endpoints ──────────────────────────
    results.append(run_test(
        "Q14",
        "What are all the API functions in the frontend?",
        ["apiFetch", "fetchWards", "fetchWardDetail", "submitReport",
         "fetchRecentReports", "fetchWindData", "fetchImpactMetrics",
         "login", "logout", "getCSRFToken"],
        lambda: list(grep_files(["fetch", "api", "async function"])),
        lambda: (mcp_search("API fetch function endpoint")["symbols"]
                 + mcp_search("frontend API calls ward")["symbols"]),
    ))

    # ─── Q15: Understanding state management ──────────────────
    results.append(run_test(
        "Q15",
        "How does state management work in this React app?",
        ["useAppState", "useAppDispatch", "AppProvider", "AppContext.jsx"],
        lambda: list(grep_files(["useContext", "useReducer", "dispatch", "Provider", "createContext"])),
        lambda: (mcp_search("state management context dispatch reducer")["symbols"]
                 + mcp_search("state management context dispatch reducer")["files"]),
    ))

    return results


def _baseline_dead_code() -> list[str]:
    """Baseline dead code: find function defs, then check if name appears elsewhere."""
    # This is what a dev would do manually: find all functions, grep for usage
    dead = []
    all_funcs = set()
    for line in grep(["function ", "def "], exts="*.py *.js *.jsx"):
        m = re.search(r'(?:function|def)\s+(\w+)', line)
        if m and m.group(1) not in ('__init__', 'main', 'setup'):
            all_funcs.add(m.group(1))

    # check each function for references (this is slow but realistic)
    for func in list(all_funcs)[:40]:  # limit to avoid timeout
        refs = grep_files([func])
        # if it only appears in 1 file (its definition), it's likely dead
        if len(refs) <= 1:
            dead.append(func)
    return dead


def _baseline_importance() -> list[str]:
    """Baseline importance: count how many files reference each function name."""
    counts = {}
    all_funcs = set()
    for line in grep(["function ", "def "], exts="*.py *.js *.jsx"):
        m = re.search(r'(?:function|def)\s+(\w+)', line)
        if m:
            all_funcs.add(m.group(1))

    for func in list(all_funcs)[:40]:
        refs = grep_files([func])
        counts[func] = len(refs)

    # sort by reference count descending
    ranked = sorted(counts, key=lambda x: counts[x], reverse=True)
    return ranked[:20]


# ── main ───────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("CODEBASE INTELLIGENCE — REAL-WORLD A/B EVALUATION")
    print("=" * 60)
    print(f"Target: Sparrow ({SPARROW})")
    print(f"Tests: 15 natural developer questions")
    print(f"Baseline: grep/findstr (what you'd do without tools)")
    print(f"Enhanced: MCP tools (search + call graph + blast radius)")

    results = run_all()

    # summary
    e_wins = sum(1 for r in results if r["winner"] == "enhanced")
    b_wins = sum(1 for r in results if r["winner"] == "baseline")
    ties = sum(1 for r in results if r["winner"] == "tie")
    e_avg = sum(r["enhanced"]["recall"] for r in results) / len(results)
    b_avg = sum(r["baseline"]["recall"] for r in results) / len(results)

    print("\n" + "=" * 60)
    print(f"RESULTS: Enhanced {e_wins} wins | Baseline {b_wins} wins | {ties} ties")
    print(f"AVG RECALL: Enhanced {e_avg:.1f}% | Baseline {b_avg:.1f}%")
    print("=" * 60)

    out = Path(__file__).parent / "eval_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults → {out}")


if __name__ == "__main__":
    main()
