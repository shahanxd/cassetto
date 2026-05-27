"""
Git intelligence — churn, blame, ownership, change coupling.

All functions shell out to git and parse the output. No git library needed.
Everything is local — no API keys, no network calls.
"""
import subprocess
import json
from collections import Counter, defaultdict
from pathlib import Path


def is_git_repo(directory: str) -> bool:
    """Check if a directory is inside a git repository."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            cwd=directory, capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_file_churn(repo_root: str, limit: int = 100) -> list[dict]:
    """Most frequently modified files. High churn = high risk."""
    try:
        result = subprocess.run(
            ['git', 'log', '--format=', '--name-only', '--diff-filter=M',
             '-n', '500'],
            cwd=repo_root, capture_output=True, text=True,
            timeout=15, errors='replace'
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    files = [f.strip() for f in result.stdout.strip().split('\n')
             if f.strip() and not _is_noise(f.strip())]

    counts = Counter(files).most_common(limit)
    return [{"file": f, "change_count": c} for f, c in counts]


def get_recent_changes(repo_root: str, days: int = 30) -> list[dict]:
    """Files modified in the last N days."""
    try:
        result = subprocess.run(
            ['git', 'log', f'--since={days} days ago',
             '--format=%H', '--name-only', '--diff-filter=M'],
            cwd=repo_root, capture_output=True, text=True,
            timeout=15, errors='replace'
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    files = set()
    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if line and not _is_noise(line) and len(line) != 40:
            files.add(line)

    return [{"file": f} for f in sorted(files)]


def get_ownership(repo_root: str) -> dict[str, dict]:
    """
    File → primary author mapping using git shortlog.
    Returns {file: {author: str, commits: int}} for each file.
    """
    try:
        result = subprocess.run(
            ['git', 'log', '--format=%ae', '--name-only', '-n', '500'],
            cwd=repo_root, capture_output=True, text=True,
            timeout=15, errors='replace'
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    ownership: dict[str, Counter] = defaultdict(Counter)
    current_author = None

    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if not line:
            current_author = None
        elif '@' in line and current_author is None:
            current_author = line
        elif current_author and not _is_noise(line):
            ownership[line][current_author] += 1

    result_map = {}
    for file, authors in ownership.items():
        top_author, count = authors.most_common(1)[0]
        result_map[file] = {
            "author": top_author,
            "commits": count,
            "total_authors": len(authors)
        }

    return result_map


def get_change_coupling(repo_root: str, min_co_changes: int = 2,
                         limit: int = 30) -> list[dict]:
    """
    Files that frequently change together in the same commit.
    If A and B always change together, they're coupled even without imports.
    """
    try:
        result = subprocess.run(
            ['git', 'log', '--format=---COMMIT---', '--name-only',
             '--diff-filter=M', '-n', '200'],
            cwd=repo_root, capture_output=True, text=True,
            timeout=15, errors='replace'
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    # parse commits into groups of files
    commits = []
    current = []
    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if line == '---COMMIT---':
            if current:
                commits.append(current)
            current = []
        elif line and not _is_noise(line):
            current.append(line)
    if current:
        commits.append(current)

    # count co-occurrences
    pairs: Counter = Counter()
    for files in commits:
        clean = sorted(set(files))
        for i, a in enumerate(clean):
            for b in clean[i+1:]:
                pairs[(a, b)] += 1

    coupled = [(a, b, count) for (a, b), count in pairs.most_common(limit)
               if count >= min_co_changes]

    return [{"file_a": a, "file_b": b, "co_changes": c}
            for a, b, c in coupled]


def get_hotspots(repo_root: str, limit: int = 15) -> list[dict]:
    """
    High-risk files: high churn + many authors = hotspot.
    Score = change_count * num_authors.
    """
    churn = get_file_churn(repo_root, limit=200)
    owner = get_ownership(repo_root)

    hotspots = []
    for item in churn:
        f = item["file"]
        cc = item["change_count"]
        ow = owner.get(f, {})
        num_authors = ow.get("total_authors", 1)
        score = cc * num_authors
        hotspots.append({
            "file": f,
            "change_count": cc,
            "authors": num_authors,
            "primary_author": ow.get("author", "unknown"),
            "risk_score": score,
        })

    hotspots.sort(key=lambda x: x["risk_score"], reverse=True)
    return hotspots[:limit]


def get_file_history(repo_root: str, file_path: str,
                      limit: int = 10) -> list[dict]:
    """Git log for a specific file — who changed it and when."""
    try:
        result = subprocess.run(
            ['git', 'log', f'-{limit}', '--format=%H|%ae|%s|%ai',
             '--', file_path],
            cwd=repo_root, capture_output=True, text=True,
            timeout=10, errors='replace'
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    entries = []
    for line in result.stdout.strip().split('\n'):
        if '|' in line:
            parts = line.split('|', 3)
            if len(parts) == 4:
                entries.append({
                    "hash": parts[0][:8],
                    "author": parts[1],
                    "message": parts[2],
                    "date": parts[3].split(' ')[0],
                })

    return entries


def _is_noise(file_path: str) -> bool:
    """Filter out files we don't care about (binary, generated, etc)."""
    noise = ('node_modules/', '__pycache__/', '.pyc', '.git/',
             'package-lock.json', '.min.js', '.map', '.sqlite3',
             'dist/', 'build/', '.cache/')
    return any(n in file_path for n in noise)
