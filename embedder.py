"""
Embedding layer — turns code text into 768-dim vectors.

Default backend is Ollama running locally (nomic-embed-text model).
Optional Voyage AI backend for better quality at the cost of API calls.
"""
import requests
from config import EMBEDDING_BACKEND, OLLAMA_URL, OLLAMA_MODEL


def embed_text(text: str) -> list[float]:
    """Embed a single string. Used for search queries."""
    if EMBEDDING_BACKEND == "voyage":
        return _embed_voyage(text)
    return _embed_ollama(text)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings. Used during indexing."""
    if EMBEDDING_BACKEND == "voyage":
        return _embed_voyage_batch(texts)
    # ollama doesn't have a native batch endpoint, so we loop.
    # progress is printed every 10 chunks to show it's not stuck.
    embeddings = []
    for i, text in enumerate(texts):
        if i % 10 == 0 and len(texts) > 10:
            print(f"  Embedding {i}/{len(texts)}...")
        embeddings.append(_embed_ollama(text))
    return embeddings


def check_embedding_ready() -> tuple[bool, str]:
    """Quick health check — is the embedding backend reachable?"""
    if EMBEDDING_BACKEND == "voyage":
        from config import VOYAGE_API_KEY
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


# ── backends ────────────────────────────────────────────────────

# reuse TCP connections to ollama — saves ~20ms per request on
# large indexes where we make thousands of calls
_session = requests.Session()


def _embed_ollama(text: str) -> list[float]:
    """Single embedding via local Ollama instance."""
    response = _session.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": OLLAMA_MODEL, "prompt": text},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def _embed_voyage_batch(texts: list[str]) -> list[list[float]]:
    """Batch embedding via Voyage AI API."""
    from config import VOYAGE_API_KEY, VOYAGE_MODEL
    try:
        import voyageai
    except ImportError:
        raise ImportError("pip install voyageai")
    client = voyageai.Client(api_key=VOYAGE_API_KEY)
    result = client.embed(texts, model=VOYAGE_MODEL, input_type="document")
    return result.embeddings


def _embed_voyage(text: str) -> list[float]:
    return _embed_voyage_batch([text])[0]
