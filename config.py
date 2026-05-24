"""
Codebase Intelligence — Configuration
Central config for all components. Override via environment variables.
"""
import os
from pathlib import Path

# --- Storage ---
DATA_DIR = Path(os.getenv("CI_DATA_DIR", str(Path.home() / ".codebase-intelligence")))

# --- Embedding ---
EMBEDDING_BACKEND = os.getenv("CI_EMBEDDING_BACKEND", "ollama")  # "ollama" or "voyage"
OLLAMA_URL = os.getenv("CI_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("CI_OLLAMA_MODEL", "nomic-embed-text")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = "voyage-code-3"

# --- Indexing ---
SKIP_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv',
    'dist', 'build', '.next', '.nuxt', 'coverage', '.pytest_cache',
    '.mypy_cache', '.tox', 'egg-info', '.eggs', '.cache',
}

SUPPORTED_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx',
    '.go', '.rs', '.java', '.rb', '.php',
    '.cs', '.cpp', '.c', '.h', '.hpp',
}

# --- Chunking ---
MAX_CHUNK_SIZE = 6000  # characters — truncate chunks larger than this
MIN_CHUNK_SIZE = 20    # characters — skip trivially small chunks
