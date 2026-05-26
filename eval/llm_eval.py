"""
Cassetto — Fair LLM Evaluation (v2)

FAIR TEST: Both conditions have access to the project code.
  1. VANILLA: LLM gets full project files dumped into context (what IDE AI does)
  2. CASSETTO: LLM gets focused Cassetto tool outputs (structured intelligence)

Both answers scored against verified ground truth.
The question: does structured code intelligence beat raw file access?
"""
import os, sys, json, time, re, requests

_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ['CASSETTO_PROJECT_ID'] = 'sparrow'

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:3b"
SPARROW = os.path.join(_PARENT, "sparrow")

# Pre-import Cassetto tools
from server import (search_code, get_call_graph_tool, blast_radius,
                    find_dead_code, get_repo_map, find_references,
                    goto_definition, explain_symbol, get_hotspots,
                    get_architecture_summary, find_entry_points,
                    get_imports, find_cycles, get_index_status)

_TOOL_MAP = {
    "search_code": search_code, "get_call_graph_tool": get_call_graph_tool,
    "blast_radius": blast_radius, "find_dead_code": find_dead_code,
    "get_repo_map": get_repo_map, "find_references": find_references,
    "goto_definition": goto_definition, "explain_symbol": explain_symbol,
    "get_hotspots": get_hotspots, "get_architecture_summary": get_architecture_summary,
    "find_entry_points": find_entry_points, "get_imports": get_imports,
    "find_cycles": find_cycles, "get_index_status": get_index_status,
}

# ── Build project dump (what an IDE context window looks like) ──

def build_project_dump() -> str:
    """Concatenate all source files into one big context string.
    This simulates what an IDE AI assistant sees when you open a project."""
    SKIP = {'node_modules', '.git', '__pycache__', '.next', 'dist', 'build',
            'migrations', '.venv', 'env'}
    EXTS = {'.py', '.js', '.jsx', '.ts', '.tsx', '.json', '.css'}

    parts = []
    total_chars = 0
    MAX_CHARS = 80000  # ~20K tokens, realistic context budget

    files = []
    for root, dirs, fnames in os.walk(SPARROW):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in sorted(fnames):
            if os.path.splitext(f)[1] in EXTS:
                files.append(os.path.join(root, f))

    for fp in sorted(files):
        try:
            content = open(fp, 'r', encoding='utf-8', errors='ignore').read()
        except Exception:
            continue

        rel = os.path.relpath(fp, SPARROW)
        # truncate large files
        if len(content) > 4000:
            content = content[:4000] + "\n... (truncated)"

        block = f"=== FILE: {rel} ===\n{content}\n"
        if total_chars + len(block) > MAX_CHARS:
            parts.append(f"\n... ({len(files) - len(parts)} more files omitted due to context limit)")
            break
        parts.append(block)
        total_chars += len(block)

    return "\n".join(parts)


# ── LLM caller ────────────────────────────────────────────────

def ask_llm(system: str, question: str, timeout: int = 180) -> str:
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "options": {"temperature": 0.1, "num_predict": 1000}
        }, timeout=timeout)
        return r.json()["message"]["content"]
    except Exception as e:
        return f"[ERROR: {e}]"


def get_cassetto_context(tools_to_call: list) -> str:
    parts = []
    for tool_name, args in tools_to_call:
        try:
            fn = _TOOL_MAP[tool_name]
            result = fn(*args) if args else fn()
            parts.append(f"### Tool: {tool_name}({', '.join(repr(a) for a in args)})\n{result}")
        except Exception as e:
            parts.append(f"### Tool: {tool_name} - ERROR: {e}")
    return "\n\n---\n\n".join(parts)


# ── Scoring ───────────────────────────────────────────────────

def score_answer(answer: str, ground_truth: dict) -> dict:
    clean = answer.replace('`', '').replace('**', '').replace('*', '')
    clean = re.sub(r'\[|\]|\(|\)', ' ', clean)
    answer_lower = clean.lower()

    facts_found = 0
    facts_total = len(ground_truth["required_facts"])
    facts_detail = []
    for fact in ground_truth["required_facts"]:
        fact_l = fact.lower()
        stem = fact_l.rsplit('.', 1)[0] if '.' in fact_l else fact_l
        found = fact_l in answer_lower or (len(stem) > 3 and stem in answer_lower)
        facts_found += found
        facts_detail.append({"fact": fact, "found": found})

    syms_found = 0
    syms_total = len(ground_truth.get("specific_symbols", []))
    for sym in ground_truth.get("specific_symbols", []):
        sym_l = sym.lower()
        stem = sym_l.rsplit('.', 1)[0] if '.' in sym_l else sym_l
        if sym_l in answer_lower or (len(stem) > 3 and stem in answer_lower):
            syms_found += 1

    accuracy = round(facts_found / facts_total * 100, 1) if facts_total else 0
    specificity = round(syms_found / syms_total * 100, 1) if syms_total else 0

    return {
        "accuracy": accuracy, "specificity": specificity,
        "facts_found": facts_found, "facts_total": facts_total,
        "symbols_found": syms_found, "symbols_total": syms_total,
        "facts_detail": facts_detail,
    }


# ── Test cases ────────────────────────────────────────────────

TESTS = [
    {
        "id": "Q1",
        "question": "Give me a high-level overview of this project: what frameworks it uses, the directory structure, and where the main entry points are.",
        "cassetto_tools": [
            ("get_architecture_summary", []),
            ("find_entry_points", []),
        ],
        "ground_truth": {
            "required_facts": ["django", "react", "manage.py", "main.jsx"],
            "specific_symbols": ["manage.py", "main.jsx", "urls.py", "App", "django", "react"],
        },
    },
    {
        "id": "Q2",
        "question": "Where is AQI (Air Quality Index) calculated? Show me the specific functions and files that compute AQI values.",
        "cassetto_tools": [
            ("search_code", ["AQI calculation air quality index"]),
            ("explain_symbol", ["getAqiTier"]),
        ],
        "ground_truth": {
            "required_facts": ["getAqiTier", "aqiUtils", "getAqiColor"],
            "specific_symbols": ["getAqiTier", "getAqiColor", "getAqiCategory", "aqiUtils.js",
                                "_pm25_to_aqi", "get_aqi_tier"],
        },
    },
    {
        "id": "Q3",
        "question": "If I refactor the apiFetch function, what other functions and files will break? Give me the complete blast radius.",
        "cassetto_tools": [
            ("blast_radius", ["apiFetch"]),
            ("find_references", ["apiFetch"]),
        ],
        "ground_truth": {
            "required_facts": ["fetchWards", "fetchWardDetail", "submitReport", "wardApi"],
            "specific_symbols": ["fetchWards", "fetchWardDetail", "fetchHotspots", "fetchCityTrend",
                                "fetchSourceMap", "submitReport", "fetchRecentReports",
                                "fetchWindData", "fetchImpactMetrics", "wardApi.js"],
        },
    },
    {
        "id": "Q4",
        "question": "Explain the _build_ward_data function: what does it do, what calls it, and what internal functions does it call?",
        "cassetto_tools": [
            ("explain_symbol", ["_build_ward_data"]),
            ("goto_definition", ["_build_ward_data"]),
        ],
        "ground_truth": {
            "required_facts": ["services.py", "get_aqi_tier", "_fallback_sources"],
            "specific_symbols": ["_build_ward_data", "get_ward_summary_list", "get_ward_detail",
                                "get_hotspots", "get_aqi_tier", "_fallback_sources",
                                "get_explainability", "services.py"],
        },
    },
    {
        "id": "Q5",
        "question": "Which files in this project have the highest churn rate and are riskiest for bugs? Which ones change the most?",
        "cassetto_tools": [
            ("get_hotspots", []),
        ],
        "ground_truth": {
            "required_facts": ["DetailPanel", "services.py"],
            "specific_symbols": ["DetailPanel.jsx", "services.py", "App.jsx", "AppContext.jsx"],
        },
    },
    {
        "id": "Q6",
        "question": "Show me the exact source code of the getAqiColor function. Where is it defined and what does it do?",
        "cassetto_tools": [
            ("goto_definition", ["getAqiColor"]),
            ("find_references", ["getAqiColor"]),
        ],
        "ground_truth": {
            "required_facts": ["aqiUtils", "getAqiTier", "color"],
            "specific_symbols": ["getAqiColor", "getAqiTier", "aqiUtils.js"],
        },
    },
    {
        "id": "Q7",
        "question": "What does services.py import? List all its dependencies, both standard library and project-internal.",
        "cassetto_tools": [],  # will be set dynamically
        "ground_truth": {
            "required_facts": ["models", "json", "django"],
            "specific_symbols": ["Ward", "AQIReading", "json", "math",
                                "django", "source_model"],
        },
    },
    {
        "id": "Q8",
        "question": "Are there any unused functions in this codebase that could be safely deleted? Find dead code.",
        "cassetto_tools": [
            ("find_dead_code", []),
        ],
        "ground_truth": {
            "required_facts": ["_has_real_data", "buildDistrictMap"],
            "specific_symbols": ["_has_real_data", "buildDistrictMap", "simulate_intervention",
                                "getAqiFillColor", "getMitigations"],
        },
    },
    {
        "id": "Q9",
        "question": "What are the most important and central functions in this codebase? Rank them by how many other functions depend on them.",
        "cassetto_tools": [
            ("get_repo_map", [20]),
        ],
        "ground_truth": {
            "required_facts": ["apiFetch", "getAqiTier"],
            "specific_symbols": ["apiFetch", "getAqiTier", "useAppState", "useAppDispatch",
                                "_get_latest_reading", "getCSRFToken", "_build_ward_data"],
        },
    },
    {
        "id": "Q10",
        "question": "Trace the full data pipeline: how does ward data flow from the Django backend API all the way to the React frontend map component?",
        "cassetto_tools": [
            ("search_code", ["ward data flow API frontend"]),
            ("explain_symbol", ["fetchWards"]),
            ("explain_symbol", ["get_ward_summary_list"]),
        ],
        "ground_truth": {
            "required_facts": ["fetchWards", "apiFetch", "WardLayer"],
            "specific_symbols": ["fetchWards", "apiFetch", "get_ward_summary_list",
                                "_build_ward_data", "WardLayer", "AppContext", "views.py"],
        },
    },
]


def run_eval():
    print("=" * 70)
    print("CASSETTO - FAIR LLM EVALUATION")
    print(f"Model: {MODEL}")
    print("Vanilla: LLM + full project files in context")
    print("Cassetto: LLM + Cassetto tool outputs")
    print("=" * 70)

    # Build project dump once
    print("\nBuilding project context dump...")
    project_dump = build_project_dump()
    dump_tokens = len(project_dump) // 4  # rough estimate
    print(f"  Project dump: {len(project_dump)} chars (~{dump_tokens} tokens)")

    # Fix Q7 imports path
    from store import get_indexed_files
    files = get_indexed_files('sparrow')
    svc = [f for f in files if 'services.py' in f and 'migration' not in f]
    if svc:
        TESTS[6]["cassetto_tools"] = [("get_imports", [svc[0]])]

    VANILLA_SYSTEM = (
        "You are a senior developer analyzing a codebase. "
        "Below are the full source files of the project. "
        "Answer the question using ONLY information from these files. "
        "Be specific: name exact function names, file names, and line numbers. "
        "Do not guess or make up names that don't appear in the code."
    )

    CASSETTO_SYSTEM = (
        "You are a senior developer with code intelligence tools. "
        "Below is structured output from codebase analysis tools. "
        "Answer the question using this analyzed context. "
        "Be specific: name exact function names, file names, and line numbers. "
        "Only reference things that appear in the tool output."
    )

    results = []
    for test in TESTS:
        tid = test["id"]
        q = test["question"]
        print(f"\n{'_'*60}")
        print(f"[{tid}] {q}")

        # VANILLA: project files in context
        print(f"  Running vanilla (project dump + question)...")
        t0 = time.time()
        vanilla_prompt = f"PROJECT SOURCE CODE:\n\n{project_dump}\n\nQUESTION: {q}"
        vanilla_answer = ask_llm(VANILLA_SYSTEM, vanilla_prompt, timeout=300)
        vanilla_time = round(time.time() - t0, 1)
        vanilla_score = score_answer(vanilla_answer, test["ground_truth"])
        print(f"  Vanilla:  acc={vanilla_score['accuracy']}% "
              f"spec={vanilla_score['specificity']}% [{vanilla_time}s]")

        # CASSETTO: tool outputs as context
        print(f"  Running Cassetto (tool outputs + question)...")
        t0 = time.time()
        context = get_cassetto_context(test["cassetto_tools"])
        cassetto_prompt = f"CODEBASE INTELLIGENCE OUTPUT:\n\n{context}\n\nQUESTION: {q}"
        cassetto_answer = ask_llm(CASSETTO_SYSTEM, cassetto_prompt, timeout=300)
        cassetto_time = round(time.time() - t0, 1)
        cassetto_score = score_answer(cassetto_answer, test["ground_truth"])
        print(f"  Cassetto: acc={cassetto_score['accuracy']}% "
              f"spec={cassetto_score['specificity']}% [{cassetto_time}s]")

        winner = "cassetto" if cassetto_score["accuracy"] > vanilla_score["accuracy"] else \
                 ("vanilla" if vanilla_score["accuracy"] > cassetto_score["accuracy"] else "tie")
        if cassetto_score["accuracy"] == vanilla_score["accuracy"]:
            winner = "cassetto" if cassetto_score["specificity"] > vanilla_score["specificity"] else \
                     ("vanilla" if vanilla_score["specificity"] > cassetto_score["specificity"] else "tie")

        print(f"  -> {winner.upper()}")

        results.append({
            "id": tid, "question": q,
            "vanilla": {"answer": vanilla_answer, **vanilla_score, "time_s": vanilla_time},
            "cassetto": {"answer": cassetto_answer, **cassetto_score, "time_s": cassetto_time},
            "ground_truth": test["ground_truth"],
            "winner": winner,
        })

    # Summary
    v_acc = sum(r["vanilla"]["accuracy"] for r in results) / len(results)
    c_acc = sum(r["cassetto"]["accuracy"] for r in results) / len(results)
    v_spec = sum(r["vanilla"]["specificity"] for r in results) / len(results)
    c_spec = sum(r["cassetto"]["specificity"] for r in results) / len(results)
    c_wins = sum(1 for r in results if r["winner"] == "cassetto")
    v_wins = sum(1 for r in results if r["winner"] == "vanilla")
    ties = sum(1 for r in results if r["winner"] == "tie")

    print(f"\n{'='*70}")
    print(f"RESULTS: Cassetto {c_wins} wins | Vanilla {v_wins} wins | {ties} ties")
    print(f"AVG ACCURACY:    Cassetto {c_acc:.1f}%  |  Vanilla {v_acc:.1f}%")
    print(f"AVG SPECIFICITY: Cassetto {c_spec:.1f}%  |  Vanilla {v_spec:.1f}%")
    print(f"{'='*70}")

    out_path = os.path.join(os.path.dirname(__file__), 'llm_eval_results.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nRaw results saved.")

    return results


if __name__ == "__main__":
    run_eval()
