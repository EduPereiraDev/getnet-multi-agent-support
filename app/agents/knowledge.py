"""Knowledge Agent: Getnet product Q&A grounded in RAG + web tools for general questions.

General questions (weather, exchange rates) are answered straight from the web tools. Getnet
questions are grounded in the local RAG index: LLM mode runs a cited tool-use loop over the
retrieved chunks; offline mode answers extractively with the most relevant official sentences.
"""

import logging
import re
import unicodedata
from typing import Any

from app.config import get_settings
from app.rag.store import Chunk, get_retriever
from app.schemas import AgentContext, AgentResult, Source, ToolCall
from app.tools import web_tools

log = logging.getLogger(__name__)

WEATHER_RE = re.compile(
    r"\b(weather|forecast|rain|raining|temperature|clima|chuva|chover|previs[aã]o do tempo"
    r"|como (?:est[aá]|vai estar|fica) o tempo|tempo (?:em|no|na|hoje|amanh[aã]))\b",
    re.IGNORECASE,
)
FX_RE = re.compile(
    r"exchange rate|\b(c[aâ]mbio|cota[cç][aã]o|euros?|d[oó]lar(es)?|dollars?|pounds?|libras?|usd|eur|gbp)\b", re.IGNORECASE
)
FX_BASES: tuple[tuple[str, str], ...] = (
    (r"\b(euros?|eur)\b", "EUR"),
    (r"\b(pounds?|libras?|gbp|sterling)\b", "GBP"),
    (r"\b(d[oó]lar(es)?|dollars?|usd)\b", "USD"),
)
TOMORROW_RE = re.compile(r"\b(tomorrow|amanh[aã])\b", re.IGNORECASE)
CITY_RE = re.compile(
    r"\b(?:in|em|no|na|for|para)\s+(.+?)(?=\s+(?:tomorrow|today|tonight|amanh[aã]|hoje|this|next|esta|nesta)\b|[?.!,;]|$)",
    re.IGNORECASE,
)
GETNET_HINTS = ("getnet", "maquininha", "card machine", "pix", "antecipa", "crediario", "link de pagamento", "taxa")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "can", "com", "como", "da", "das", "de", "do", "does", "dos",
    "e", "em", "for", "from", "get", "getnet", "how", "i", "in", "into", "is", "it", "my", "na", "no", "o",
    "of", "on", "or", "os", "para", "por", "posso", "qual", "que", "the", "to", "um", "uma", "using",
    "via", "what", "whats", "when", "where", "which", "with", "work", "you", "your", "s", "need",
    "should", "won", "t", "me", "this", "that", "there", "between", "difference",
}
MAX_SENTENCES = 6
MAX_CHARS = 700
RELEVANCE_RATIO = 0.5
SENTENCE_SPLIT_RE = re.compile(r"(?<!\bex\.)(?<=[.!?])\s+")


def _fold(text: str) -> str:
    """Lowercase, accent-insensitive form used for matching."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _terms(text: str) -> list[str]:
    seen: list[str] = []
    for tok in re.findall(r"[a-z0-9]+", _fold(text)):
        if tok not in STOPWORDS and (len(tok) > 2 or tok.isdigit()) and tok not in seen:
            seen.append(tok)
    return seen


def _matches(term: str, folded: str) -> bool:
    # Prefix match tolerates simple inflections (installment/installments, conecta/conectar).
    return re.search(rf"\b{re.escape(term[:-1] if len(term) > 4 else term)}", folded) is not None


def is_weather(text: str) -> bool:
    return bool(WEATHER_RE.search(text))


def is_fx(text: str) -> bool:
    return bool(FX_RE.search(text))


def extract_city(text: str) -> str | None:
    match = CITY_RE.search(text)
    if not match:
        return None
    city = re.sub(r"^(the city of|a cidade de)\s+", "", match.group(1).strip(), flags=re.IGNORECASE)
    return city or None


def fx_base(text: str) -> str:
    for pattern, code in FX_BASES:
        if re.search(pattern, text, re.IGNORECASE):
            return code
    return "USD"


def _unique_sources(chunks: list[Chunk]) -> list[Source]:
    sources: list[Source] = []
    for c in chunks:
        src = Source(title=c.title, url=c.url)
        if src not in sources:
            sources.append(src)
    return sources


def _candidates(terms: list[str], chunks: list[Chunk]) -> list[dict[str, Any]]:
    """Split chunks into clean sentences; each carries the terms it (or its section heading) mentions."""
    out: list[dict[str, Any]] = []
    seen: list[str] = []
    for ci, chunk in enumerate(chunks):
        title, heading = "", ""
        for line in chunk.text.splitlines():
            line = line.strip().lstrip("-• ").strip()
            if line.startswith("# "):
                title, heading = _fold(line), ""
                continue
            if line.startswith("#"):
                heading = _fold(line)
                continue
            if not line or line.lower().startswith("fonte") or "http" in line:
                continue
            for sentence in SENTENCE_SPLIT_RE.split(line):
                sentence = sentence.strip()
                key = _fold(sentence)
                # Skip fragments cut by chunk overlap and sentences already seen in an earlier chunk.
                if len(sentence) < 20 or sentence[0].islower() or any(key in s for s in seen):
                    continue
                seen.append(key)
                own = {t for t in terms if _matches(t, key)}
                inherited = {t for t in terms if t not in own and _matches(t, f"{title} {heading}")}
                score = 2 * len(own) + len(inherited)
                if score:
                    out.append({"pos": len(out), "text": sentence, "chunk": ci, "own": own, "score": score})
    return out


def select_sentences(query: str, chunks: list[Chunk]) -> tuple[list[str], list[Chunk]]:
    """Extract the most relevant sentences (original order) and the chunks they came from."""
    terms = _terms(query)
    candidates = _candidates(terms, chunks)
    if not candidates:
        return [], []
    # Rank by term overlap, then by chunk rank (retrieval score), then position.
    ranked = sorted(candidates, key=lambda c: (-c["score"], c["chunk"], c["pos"]))
    chosen: list[dict[str, Any]] = []
    # 1) Coverage: every question term mentioned in the content keeps at least one sentence.
    for term in terms:
        if len(chosen) >= MAX_SENTENCES or any(term in c["own"] for c in chosen):
            continue
        best = next((c for c in ranked if term in c["own"]), None)
        if best:
            chosen.append(best)
    # 2) Fill with the best remaining sentences within the size budget.
    for cand in ranked:
        if len(chosen) >= MAX_SENTENCES:
            break
        if cand in chosen:
            continue
        if sum(len(c["text"]) for c in chosen) + len(cand["text"]) > MAX_CHARS and len(chosen) >= 3:
            continue
        chosen.append(cand)
    chosen.sort(key=lambda c: c["pos"])
    used = [chunks[i] for i in sorted({c["chunk"] for c in chosen})]
    return [c["text"] for c in chosen], used



class KnowledgeAgent:
    name = "knowledge"

    def run(self, ctx: AgentContext) -> AgentResult:
        text = ctx.masked_message
        if is_weather(text):
            return self._weather(text)
        if is_fx(text):
            return self._fx(text)

        settings = get_settings()
        chunks = get_retriever().search(text, k=settings.rag_top_k)
        rag_call = ToolCall(tool="search_knowledge_base", ok=True, args={"query": text, "hits": len(chunks)})
        if settings.resolved_mode == "llm":
            try:
                return self._run_llm(ctx, chunks, rag_call)
            except Exception as exc:  # noqa: BLE001 - any LLM failure degrades to offline
                log.warning("knowledge LLM path failed, falling back to offline: %s", exc)
        if chunks:
            return self._extractive(ctx, chunks, rag_call)
        return self._web_fallback(text, rag_call)

    # General-purpose tools ----------------------------------------------------------------
    def _weather(self, text: str) -> AgentResult:
        city = extract_city(text)
        if not city:
            return AgentResult(
                agent=self.name,
                answer="Which city would you like the weather forecast for?",
                confidence=0.3,
            )
        day_offset = 1 if TOMORROW_RE.search(text) else 0
        args = {"city": city, "day_offset": day_offset}
        res = web_tools.get_weather(city, day_offset=day_offset)
        call = ToolCall(tool="get_weather", ok=bool(res.get("ok")), args=args, error=res.get("error"))
        if not res.get("ok"):
            return AgentResult(
                agent=self.name,
                answer=f"I couldn't get the weather forecast for {city} right now. Please try again later.",
                tool_calls=[call],
                confidence=0.3,
            )
        place = ", ".join(p for p in (res["city"], res.get("country", "")) if p)
        answer = (
            f"Weather forecast for {place} on {res['date']}: {res['condition']}, "
            f"min {res['temp_min_c']}°C / max {res['temp_max_c']}°C, "
            f"{res['precipitation_probability_pct']}% chance of precipitation.\n"
            "Source: Open-Meteo (https://open-meteo.com)"
        )
        return AgentResult(
            agent=self.name,
            answer=answer,
            sources=[Source(title="Open-Meteo forecast", url="https://open-meteo.com")],
            tool_calls=[call],
            confidence=0.9,
            data={"weather": res},
        )

    def _fx(self, text: str) -> AgentResult:
        base = fx_base(text)
        res = web_tools.get_exchange_rate(base, "BRL")
        call = ToolCall(
            tool="get_exchange_rate", ok=bool(res.get("ok")), args={"base": base, "quote": "BRL"},
            error=res.get("error"),
        )
        if not res.get("ok"):
            return AgentResult(
                agent=self.name,
                answer=f"I couldn't get the {base}/BRL exchange rate right now. Please try again later.",
                tool_calls=[call],
                confidence=0.3,
            )
        answer = (
            f"1 {base} = R$ {float(res['rate']):.4f} ({res['date']}), ECB reference rate.\n"
            "Source: Frankfurter (https://frankfurter.dev)"
        )
        return AgentResult(
            agent=self.name,
            answer=answer,
            sources=[Source(title="Frankfurter exchange rates (ECB)", url="https://frankfurter.dev")],
            tool_calls=[call],
            confidence=0.9,
            data={"exchange_rate": res},
        )

    def _web_fallback(self, text: str, rag_call: ToolCall) -> AgentResult:
        about_getnet = any(h in _fold(text) for h in GETNET_HINTS)
        query = f"Getnet {text}" if about_getnet else text
        res = web_tools.web_search(query, max_results=5)
        call = ToolCall(tool="web_search", ok=bool(res.get("ok")), args={"query": query}, error=res.get("error"))
        results = [r for r in res.get("results", []) if r.get("url")][:3] if res.get("ok") else []
        if not results:
            return AgentResult(
                agent=self.name,
                answer=(
                    "I couldn't find this in Getnet's official content. Please contact Getnet's "
                    "Central de Atendimento for help."
                ),
                tool_calls=[rag_call, call],
                confidence=0.3,
            )
        lines = ["Here is what I found on the web:"]
        for r in results:
            lines.append(f"- {r['title']}: {r.get('snippet', '').strip()} ({r['url']})")
        return AgentResult(
            agent=self.name,
            answer="\n".join(lines),
            sources=[Source(title=r["title"] or r["url"], url=r["url"]) for r in results],
            tool_calls=[rag_call, call],
            confidence=0.5 if about_getnet else 0.7,
        )

    # Getnet knowledge: LLM path -----------------------------------------------------------
    def _run_llm(self, ctx: AgentContext, chunks: list[Chunk], rag_call: ToolCall) -> AgentResult:
        from app.llm.client import get_llm, load_prompt

        context = "\n\n".join(f"[{i}] {c.title} ({c.url})\n{c.text}" for i, c in enumerate(chunks, 1))
        previous = "\n\n".join(f"[{r.agent}] {r.answer}" for r in ctx.previous)
        user_text = (
            f"Question:\n{ctx.masked_message}\n\n"
            f"Context chunks (Getnet official content):\n{context or '(no matching content)'}\n\n"
            + (f"Earlier agent outputs (do not repeat them, add official guidance):\n{previous}\n\n" if previous else "")
            + f"Focus for this step: {ctx.instruction or 'answer the question with citations'}"
        )
        tools = [{"name": n, **spec} for n, (_fn, spec) in web_tools.WEB_TOOLS.items()]

        def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
            fn = getattr(web_tools, name, None) if name in web_tools.WEB_TOOLS else None
            if fn is None:
                return {"ok": False, "error": f"unknown tool {name}"}
            return fn(**args)

        answer, calls = get_llm().run_tools(load_prompt("knowledge"), user_text, tools, execute)
        if chunks:
            confidence = 0.85
        else:
            confidence = 0.6 if any(c.ok for c in calls) else 0.3
        return AgentResult(
            agent=self.name,
            answer=answer,
            sources=_unique_sources(chunks),
            tool_calls=[rag_call, *calls],
            confidence=confidence,
        )

    # Getnet knowledge: offline extractive path --------------------------------------------
    def _extractive(self, ctx: AgentContext, chunks: list[Chunk], rag_call: ToolCall) -> AgentResult:
        query = f"{ctx.masked_message} {ctx.instruction}".strip()
        # Keep only chunks reasonably close to the best hit; weak tail hits add noise.
        relevant = [c for c in chunks if c.score >= chunks[0].score * RELEVANCE_RATIO] or chunks[:1]
        sentences, used = select_sentences(query, relevant)
        if not sentences:
            sentences, used = [chunks[0].text.strip()[:MAX_CHARS]], chunks[:1]
        follows_support = any(r.agent == "support" for r in ctx.previous)
        header = "Official Getnet guidance:" if follows_support else "According to Getnet's official content:"
        sources = _unique_sources(used)
        body = "\n".join(f"- {s}" for s in sentences)
        cites = "\n".join(f"Source: {s.url}" for s in sources)
        return AgentResult(
            agent=self.name,
            answer=f"{header}\n{body}\n{cites}",
            sources=sources,
            tool_calls=[rag_call],
            confidence=0.75,
        )
