"""
Cassetto — central config. Override anything here with env vars.
"""
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("CASSETTO_DATA_DIR", str(Path.home() / ".cassetto")))

# embedding
EMBEDDING_BACKEND = os.getenv("CASSETTO_EMBEDDING_BACKEND", "ollama")
OLLAMA_URL = os.getenv("CASSETTO_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("CASSETTO_OLLAMA_MODEL", "nomic-embed-text")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = "voyage-code-3"

# directories to skip during indexing
SKIP_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv',
    'dist', 'build', '.next', '.nuxt', 'coverage', '.pytest_cache',
    '.mypy_cache', '.tox', 'egg-info', '.eggs', '.cache',
}

# file types we know how to parse
SUPPORTED_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx',
    '.go', '.rs', '.java', '.rb', '.php',
    '.cs', '.cpp', '.c', '.h', '.hpp',
}

MAX_CHUNK_SIZE = 6000   # truncate huge functions beyond this
MIN_CHUNK_SIZE = 20     # ignore trivially small chunks
