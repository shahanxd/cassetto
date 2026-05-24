"""
Codebase Intelligence — Embedder
Generates vector embeddings for code chunks using either:
  - Ollama (local, default) with nomic-embed-text
  - Voyage AI (API, optional upgrade) with voyage-code-3
"""
import requests


def embed_text(text: str) -> list[float]:
    """Get embedding vector for a single text."""
    from config import EMBEDDING_BACKEND
    if EMBEDDING_BACKEND == "voyage":
        return _embed_voyage(text)
    return _embed_ollama(text)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts. Returns list of embedding vectors."""
    from config import EMBEDDING_BACKEND
    if EMBEDDING_BACKEND == "voyage":
        return _embed_voyage_batch(texts)
    # Ollama doesn't support true batching — loop with progress
    embeddings = []
    for i, text in enumerate(texts):
        if i % 10 == 0 and len(texts) > 10:
            print(f"  Embedding {i}/{len(texts)}...")
        embeddings.append(_embed_ollama(text))
    return embeddings


def check_embedding_ready() -> tuple[bool, str]:
    """Verify that the embedding backend is available."""
    from config import EMBEDDING_BACKEND, OLLAMA_URL, VOYAGE_API_KEY
    if EMBEDDING_BACKEND == "voyage":
        if not VOYAGE_API_KEY:
            return False, "VOYAGE_API_KEY env var not set"
        return True, "Voyage AI ready"
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            return True, "Ollama ready"
        return False, f"Ollama returned status {r.status_code}"
    except requests.ConnectionError:
        return False, "Ollama not running. Start with: ollama serve"
    except Exception as e:
        return False, f"Ollama check failed: {e}"


# --- Private embedding backends ---

def _embed_ollama(text: str) -> list[float]:
    """Get embedding via local Ollama instance."""
    from config import OLLAMA_URL, OLLAMA_MODEL
    response = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": OLLAMA_MODEL, "prompt": text},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def _embed_voyage_batch(texts: list[str]) -> list[list[float]]:
    """Batch embed via Voyage AI API."""
    from config import VOYAGE_API_KEY, VOYAGE_MODEL
    try:
        import voyageai
    except ImportError:
        raise ImportError(
            "voyageai package required for Voyage backend. "
            "Install with: pip install voyageai"
        )
    client = voyageai.Client(api_key=VOYAGE_API_KEY)
    result = client.embed(texts, model=VOYAGE_MODEL, input_type="document")
    return result.embeddings


def _embed_voyage(text: str) -> list[float]:
    """Single-text embed via Voyage AI."""
    return _embed_voyage_batch([text])[0]
