"""RAG ingestion entry point: `python -m app.rag.ingest`.

Pipeline: data/seed/*.md (+ data/sources.yaml pages when INGEST_ONLINE=1) → clean text
→ chunk (~800 chars, ~150 overlap, paragraph-first) → TF-IDF index persisted to settings.index_dir.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml
from bs4 import BeautifulSoup

from app.config import DATA_DIR, get_settings
from app.rag.store import Chunk, TfidfRetriever

SEED_DIR = DATA_DIR / "seed"
SOURCES_FILE = DATA_DIR / "sources.yaml"
USER_AGENT = "Mozilla/5.0 (compatible; getnet-support-ingest/0.1)"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150


@dataclass
class Document:
    title: str
    url: str
    text: str


def load_seed(seed_dir: Path = SEED_DIR) -> list[Document]:
    docs = []
    for path in sorted(seed_dir.glob("*.md")):
        meta: dict[str, str] = {}
        lines = path.read_text(encoding="utf-8").splitlines()
        while lines and re.match(r"^(title|url):", lines[0]):
            key, _, value = lines.pop(0).partition(":")
            meta[key] = value.strip()
        text = "\n".join(lines).strip()
        if text:
            docs.append(Document(meta.get("title", path.stem), meta.get("url", ""), text))
    return docs


def _normalise(text: str) -> str:
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def fetch_url(url: str, client: httpx.Client | None = None) -> Document | None:
    """Fetch a page and keep its main text; returns None on any failure."""
    try:
        if client is None:
            with httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as c:
                resp = c.get(url)
        else:
            resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "svg", "form"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    root = soup.find("main") or soup.body or soup
    text = _normalise(root.get_text("\n"))
    return Document(title, url, text) if len(text) > 200 else None


def load_sources(path: Path = SOURCES_FILE) -> list[str]:
    groups = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [url for urls in groups.values() for url in urls]


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split into ~size-char windows, preferring paragraph/sentence boundaries, with overlap."""
    text = _normalise(text)
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))
            if cut > size // 2:
                end = start + cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        # Begin the overlapped window on a word boundary.
        space = text.find(" ", start, end)
        if space != -1:
            start = space + 1
    return [c for c in chunks if c]


def build_index(index_dir: Path | None = None, docs: list[Document] | None = None) -> TfidfRetriever:
    settings = get_settings()
    index_dir = index_dir or settings.index_dir
    if docs is None:
        docs = load_seed()
        if settings.ingest_online:
            docs += _fetch_online()
    chunks = [Chunk(text=piece, title=d.title, url=d.url) for d in docs for piece in chunk_text(d.text)]
    retriever = TfidfRetriever.build(chunks)
    retriever.save(index_dir)
    return retriever


def _fetch_online() -> list[Document]:
    docs = []
    with httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for url in load_sources():
            doc = fetch_url(url, client)
            print(f"  {'ok  ' if doc else 'skip'} {url}")
            if doc:
                docs.append(doc)
    return docs


def main() -> int:
    settings = get_settings()
    docs = load_seed()
    if settings.ingest_online:
        docs += _fetch_online()
    retriever = build_index(settings.index_dir, docs)
    print(f"ingest: {len(docs)} docs, {len(retriever.chunks)} chunks → {settings.index_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
