"""Local knowledge index: TF-IDF (word + char n-grams) with cosine similarity.

Offline and deterministic. `Retriever` is the swap point for dense embeddings / pgvector in production.
"""

import json
import pickle
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from app.config import get_settings

CHUNKS_FILE = "chunks.json"
MODEL_FILE = "tfidf.pkl"


@dataclass
class Chunk:
    text: str
    title: str
    url: str
    score: float = 0.0


class Retriever(Protocol):
    def search(self, query: str, k: int = 4) -> list[Chunk]: ...


# The corpus is Portuguese with English key terms, so filter function words in both languages.
PT_STOP_WORDS = """a ao aos as ate com como da das de do dos e ela ele em entre esta este eu faco foi ha isso ja
la mais mas me meu minha muito na nas nao no nos o os ou para pela pelo por pode posso qual quando que
quem se sem ser seu sua tem um uma uns umas voce voces hoje amanha esta estou""".split()
STOP_WORDS = sorted(ENGLISH_STOP_WORDS | set(PT_STOP_WORDS))


def _vectorizers() -> tuple[TfidfVectorizer, TfidfVectorizer]:
    common = {"strip_accents": "unicode", "lowercase": True, "sublinear_tf": True}
    return (
        TfidfVectorizer(analyzer="word", ngram_range=(1, 2), stop_words=STOP_WORDS, **common),
        TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), **common),
    )


def _index_text(chunk: Chunk) -> str:
    return f"{chunk.title}\n{chunk.text}"


class TfidfRetriever:
    def __init__(
        self, chunks: list[Chunk], word: TfidfVectorizer, char: TfidfVectorizer, matrix, min_score: float
    ):
        self.chunks = chunks
        self.word = word
        self.char = char
        self.matrix = matrix
        self.min_score = min_score

    @classmethod
    def build(cls, chunks: list[Chunk], min_score: float | None = None) -> "TfidfRetriever":
        if not chunks:
            raise ValueError("cannot build an index without chunks")
        word, char = _vectorizers()
        texts = [_index_text(c) for c in chunks]
        matrix = cls._stack(word.fit_transform(texts), char.fit_transform(texts))
        threshold = get_settings().rag_min_score if min_score is None else min_score
        return cls(chunks, word, char, matrix, threshold)

    @staticmethod
    def _stack(word_m, char_m):
        # Each block is L2-normalised; scaling by 1/sqrt(2) keeps the stacked rows unit-length.
        return (hstack([word_m, char_m]) / np.sqrt(2)).tocsr()

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        if not query.strip():
            return []
        q_word = self.word.transform([query])
        q = self._stack(q_word, self.char.transform([query]))
        scores = (self.matrix @ q.T).toarray().ravel()
        # Char n-grams alone inflate scores for off-topic text: require at least one shared content word.
        n_word = len(self.word.vocabulary_)
        word_overlap = (self.matrix[:, :n_word] @ q_word.T).toarray().ravel()
        scores[word_overlap <= 0] = 0.0
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        return [
            Chunk(
                text=self.chunks[i].text,
                title=self.chunks[i].title,
                url=self.chunks[i].url,
                score=round(float(scores[i]), 4),
            )
            for i in order[:k]
            if scores[i] >= self.min_score
        ]

    def save(self, index_dir: Path) -> None:
        index_dir.mkdir(parents=True, exist_ok=True)
        payload = [asdict(c) for c in self.chunks]
        (index_dir / CHUNKS_FILE).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        with (index_dir / MODEL_FILE).open("wb") as fh:
            pickle.dump({"word": self.word, "char": self.char, "matrix": self.matrix}, fh)

    @classmethod
    def load(cls, index_dir: Path, min_score: float | None = None) -> "TfidfRetriever":
        chunks = [Chunk(**c) for c in json.loads((index_dir / CHUNKS_FILE).read_text(encoding="utf-8"))]
        with (index_dir / MODEL_FILE).open("rb") as fh:
            model = pickle.load(fh)  # trusted: written locally by `save`
        threshold = get_settings().rag_min_score if min_score is None else min_score
        return cls(chunks, model["word"], model["char"], model["matrix"], threshold)


def index_exists(index_dir: Path) -> bool:
    return (index_dir / CHUNKS_FILE).exists() and (index_dir / MODEL_FILE).exists()


@lru_cache
def get_retriever() -> Retriever:
    index_dir = get_settings().index_dir
    if index_exists(index_dir):
        return TfidfRetriever.load(index_dir)
    from app.rag.ingest import build_index  # local import: ingest depends on this module

    return build_index(index_dir)
