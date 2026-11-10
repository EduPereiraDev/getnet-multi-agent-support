"""Offline retrieval tests: index built from data/seed into a temp dir."""

from itertools import pairwise

import httpx
import pytest
import respx

from app.rag.ingest import build_index, chunk_text, fetch_url, load_seed
from app.rag.store import TfidfRetriever, get_retriever

MAQUININHAS = "https://site.getnet.com.br/todas-as-maquininhas/"


@pytest.fixture(scope="module")
def retriever(tmp_path_factory) -> TfidfRetriever:
    return build_index(tmp_path_factory.mktemp("index"))


def test_seed_has_title_and_url():
    docs = load_seed()
    assert len(docs) >= 10
    assert all(d.title and d.url.startswith("https://") for d in docs)


@pytest.mark.parametrize(
    ("query", "url_fragment"),
    [
        ("What is the difference between Get Clássica and Get Smart?", "todas-as-maquininhas"),
        ("Do I need a bank account to receive my sales via Pix?", "/pix/"),
        ("How does receivables advance antecipação work?", "antecipacao-de-vendas"),
        ("My card machine won't connect to the internet", "operacional"),
        ("Can I sell through WhatsApp using the Payment Link?", "link-de-pagamento"),
        ("What is Getnet?", "getnet.net"),
    ],
)
def test_top_chunk_url(retriever, query, url_fragment):
    top = retriever.search(query)[0]
    assert url_fragment in top.url
    assert top.score > 0


def test_maquininhas_chunk_mentions_both_machines(retriever):
    results = retriever.search("difference between Get Clássica and Get Smart")
    assert results[0].url == MAQUININHAS
    joined = " ".join(c.text for c in results if c.url == MAQUININHAS)
    assert "Get Clássica" in joined and "Get Smart" in joined


def test_crediario_installments(retriever):
    top = retriever.search("How many installments can I offer with crediário?")[0]
    assert "crediario" in top.url
    assert "48" in top.text


def test_connectivity_chunk_has_troubleshooting(retriever):
    top = retriever.search("card machine won't connect to the internet")[0]
    assert "não conecta" in top.text or "Wi-Fi" in top.text


def test_irrelevant_query_is_filtered(retriever):
    assert retriever.search("Write me a poem about dragons.") == []
    assert retriever.search("   ") == []


def test_results_sorted_and_limited(retriever):
    results = retriever.search("taxas maquininha débito crédito", k=3)
    assert 0 < len(results) <= 3
    assert [c.score for c in results] == sorted((c.score for c in results), reverse=True)


def test_index_roundtrip_is_deterministic(retriever, tmp_path):
    retriever.save(tmp_path)
    loaded = TfidfRetriever.load(tmp_path)
    query = "Pix por aproximação"
    assert [(c.url, c.score) for c in loaded.search(query)] == [
        (c.url, c.score) for c in retriever.search(query)
    ]


def test_chunker_overlap_and_size():
    paragraphs = [f"Parágrafo {i}. " + "texto de exemplo " * 12 for i in range(20)]
    chunks = chunk_text("\n\n".join(paragraphs), size=300, overlap=80)
    assert len(chunks) > 3
    assert all(len(c) <= 300 for c in chunks)
    for prev, nxt in pairwise(chunks):
        assert nxt[:20] in prev, "consecutive chunks must overlap"


def test_chunker_short_text_single_chunk():
    assert chunk_text("curto") == ["curto"]
    assert chunk_text("") == []


def test_get_retriever_builds_when_missing(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "index_dir", tmp_path / "idx")
    get_retriever.cache_clear()
    try:
        r = get_retriever()
        assert (tmp_path / "idx" / "chunks.json").exists()
        assert r.search("Get Tap")[0].url.endswith("/get-tap/")
    finally:
        get_retriever.cache_clear()


@respx.mock
def test_fetch_url_strips_chrome_and_skips_failures():
    html = (
        "<html><head><title>Pix | Getnet</title><style>.x{}</style></head><body>"
        "<nav>menu</nav><header>topo</header><main><p>" + "Receba via Pix na Getnet. " * 20 + "</p></main>"
        "<script>track()</script><footer>rodapé</footer></body></html>"
    )
    respx.get("https://example.test/pix").mock(return_value=httpx.Response(200, text=html))
    respx.get("https://example.test/down").mock(return_value=httpx.Response(500))
    doc = fetch_url("https://example.test/pix")
    assert doc is not None and doc.title == "Pix | Getnet"
    assert "Receba via Pix" in doc.text
    assert not any(noise in doc.text for noise in ("menu", "topo", "track", "rodapé"))
    assert fetch_url("https://example.test/down") is None
