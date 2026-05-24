"""
Codebase Intelligence — Naive Chunker (Stage 1)
Splits source files into chunks using simple regex heuristics.
Replaced by ast_chunker.py in Stage 2.
"""
import hashlib
from pathlib import Path
from dataclasses import dataclass
from config import SUPPORTED_EXTENSIONS, MIN_CHUNK_SIZE


@dataclass
class Chunk:
    """A chunk of source code extracted from a file."""
    id: str
    file: str
    symbol: str
    symbol_type: str
    chunk: str
    start_line: int
    end_line: int
    language: str
    ast_hash: str  # In Stage 1, this is just a content hash (no real AST)


def chunk_file(file_path: str) -> list[Chunk]:
    """
    Split a source file into chunks based on line-level heuristics.
    Each chunk roughly corresponds to a function, class, or top-level block.
    """
    path = Path(file_path)
    if path.suffix not in SUPPORTED_EXTENSIONS:
        return []

    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []

    lines = content.split('\n')
    language = _get_language(path.suffix)
    chunks = []

    # Find split points — lines that look like symbol definitions
    split_lines = [0]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _is_definition_line(stripped):
            split_lines.append(i)
    split_lines.append(len(lines))

    # Create chunks from split points
    for i in range(len(split_lines) - 1):
        start = split_lines[i]
        end = split_lines[i + 1]
        chunk_lines = lines[start:end]
        chunk_text = '\n'.join(chunk_lines).strip()

        if len(chunk_text) < MIN_CHUNK_SIZE:
            continue

        # Extract symbol name from first meaningful line
        first_line = chunk_lines[0].strip() if chunk_lines else ''
        symbol = _extract_symbol_name(first_line) or f"chunk_{start}"
        symbol_type = _guess_symbol_type(first_line)

        # Content hash for change detection
        content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:16]
        chunk_id = hashlib.sha256(
            f"{file_path}:{symbol}:{start}".encode()
        ).hexdigest()[:16]

        chunks.append(Chunk(
            id=chunk_id,
            file=file_path,
            symbol=symbol,
            symbol_type=symbol_type,
            chunk=chunk_text,
            start_line=start,
            end_line=end,
            language=language,
            ast_hash=content_hash,
        ))

    # If no chunks found (e.g. config file), treat whole file as one chunk
    if not chunks and content.strip():
        file_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        chunk_id = hashlib.sha256(f"{file_path}:module_level".encode()).hexdigest()[:16]
        chunks.append(Chunk(
            id=chunk_id,
            file=file_path,
            symbol='module_level',
            symbol_type='module',
            chunk=content[:6000],
            start_line=0,
            end_line=len(lines),
            language=language,
            ast_hash=file_hash,
        ))

    return chunks


def _is_definition_line(stripped: str) -> bool:
    """Check if a line looks like the start of a code symbol definition."""
    keywords = [
        'def ', 'class ', 'function ', 'async function ',
        'const ', 'let ', 'var ',
        'export function', 'export const', 'export default',
        'public ', 'private ', 'protected ',
        'func ',  # Go
        'fn ',    # Rust
    ]
    return any(stripped.startswith(kw) for kw in keywords)


def _extract_symbol_name(line: str) -> str | None:
    """Try to extract a symbol name from a definition line."""
    for keyword in ['def ', 'class ', 'function ', 'async function ',
                    'const ', 'let ', 'var ', 'func ', 'fn ']:
        if keyword in line:
            after = line.split(keyword, 1)[1]
            # Take the first word-like token
            name = after.split('(')[0].split(':')[0].split(' ')[0].split('=')[0].strip()
            return name if name else None
    return None


def _guess_symbol_type(line: str) -> str:
    """Guess the symbol type from the first line of a chunk."""
    stripped = line.strip()
    if stripped.startswith('class '):
        return 'class'
    if stripped.startswith(('def ', 'function ', 'async function ', 'func ', 'fn ')):
        return 'function'
    if stripped.startswith(('const ', 'let ', 'var ')):
        return 'variable'
    if stripped.startswith(('export ', 'public ', 'private ', 'protected ')):
        return 'export'
    return 'module'


def _get_language(suffix: str) -> str:
    """Map file extension to language name."""
    lang_map = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.tsx': 'typescript', '.jsx': 'javascript', '.go': 'go',
        '.rs': 'rust', '.java': 'java', '.rb': 'ruby',
        '.php': 'php', '.cs': 'csharp', '.cpp': 'cpp',
        '.c': 'c', '.h': 'c', '.hpp': 'cpp',
    }
    return lang_map.get(suffix, suffix.lstrip('.'))
