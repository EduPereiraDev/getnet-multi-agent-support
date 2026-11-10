"""Knowledge Agent: Getnet product Q&A grounded in RAG + web tools for general questions.

Skeleton — implementation tracked in specs/03-tasks.md (T-08, T-09, T-10).
"""

from app.schemas import AgentContext, AgentResult


class KnowledgeAgent:
    name = "knowledge"

    def run(self, ctx: AgentContext) -> AgentResult:
        # TODO(T-10): retrieve from RAG index; if general question → web/weather/FX tools;
        # LLM mode generates a grounded, cited answer; offline mode answers extractively.
        return AgentResult(
            agent=self.name,
            answer="[knowledge agent pending implementation]",
            confidence=0.5,
        )
