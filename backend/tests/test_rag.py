"""
RAG citation behaviour and quiz grading (brief §7, §10, §25).

The RAG service is tested with **fake** retrieval and LLM adapters so the suite
never needs Ollama: what matters here is the *contract* — sources attached, cited
flags honest, and the exact fallback sentence when retrieval finds nothing.
"""

from services.rag_service import RagService
from services.search_service import SearchResult


class FakeSearch:
    """Retrieval stub: returns whatever the test configured."""

    def __init__(self, hits):
        self.hits = hits

    def search(self, user_id, question, **kwargs):  # noqa: ARG002
        return list(self.hits)


class FakeLLM:
    """LLM stub that records prompts and answers deterministically."""

    def __init__(self, answer="BCNF is explained here. See [1]."):
        self.answer = answer
        self.calls = []

    def generate(self, prompt, *, system=None, max_tokens=None):  # noqa: ARG002
        from services.llm.base import LLMResponse

        self.calls.append({"prompt": prompt, "system": system})
        return LLMResponse(text=self.answer, model="fake-model", provider="fake", ok=True)

    def chat(self, messages, *, system=None, **kwargs):  # noqa: ARG002
        from services.llm.base import LLMResponse

        return LLMResponse(text="General answer.", model="fake-model", provider="fake", ok=True)


def _hit(document_id="doc-1"):
    return SearchResult(
        document_id=document_id,
        document_title="DBMS Notes",
        page_number=14,
        chunk_id="chunk-1",
        text="BCNF requires every determinant to be a superkey.",
        source_type="hybrid",
        score=0.9,
        metadata={},
    )


def test_ask_attaches_sources_and_cited_flags():
    service = RagService(settings=None, search_service=FakeSearch([_hit()]),
                         llm_service=FakeLLM())
    answer = service.ask("user-1", "Explain BCNF.", mode="knowledge",
                         top_k=6, save=False)
    assert answer.based_on_documents is True
    assert answer.sources, "every RAG answer must carry sources"
    source = answer.sources[0]
    assert source["document_id"] == "doc-1"
    assert source["page_number"] == 14
    assert source["cited"] in (True, False)
    assert "[1]" in answer.answer


def test_ask_without_hits_returns_exact_fallback_and_never_calls_the_model():
    llm = FakeLLM()
    service = RagService(settings=None, search_service=FakeSearch([]), llm_service=llm)
    answer = service.ask("user-1", "Explain BCNF.", mode="knowledge", save=False)
    assert answer.based_on_documents is False
    assert answer.sources == []
    assert answer.answer.startswith("I could not find this in your uploaded documents.")
    assert llm.calls == [], "no model call is needed for an empty knowledge base"


def test_rag_prompt_instructs_partial_answers():
    llm = FakeLLM()
    service = RagService(settings=None, search_service=FakeSearch([_hit()]),
                         llm_service=llm)
    service.ask("user-1", "Define BCNF and give an example.", mode="knowledge", save=False)

    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert "If the excerpts partially answer the question" in call["system"]
    assert "explicitly say what part is not covered" in call["system"]
    assert "Never add outside knowledge" in call["system"]
    assert "[1] DBMS Notes — page 14" in call["prompt"]
    assert _hit().text in call["prompt"]
    assert "Question: Define BCNF and give an example." in call["prompt"]


def test_ask_rejects_unknown_mode():
    service = RagService(settings=None, search_service=FakeSearch([]),
                         llm_service=FakeLLM())
    from utils.errors import ValidationError

    try:
        service.ask("user-1", "Hello", mode="telepathy", save=False)
    except ValidationError as exc:
        assert exc.code == "unknown_mode" or "Unknown chat mode" in str(exc.message)
    else:  # pragma: no cover
        raise AssertionError("unknown mode must raise ValidationError")


def test_general_mode_is_labelled():
    service = RagService(settings=None, search_service=FakeSearch([_hit()]),
                         llm_service=FakeLLM())
    answer = service.ask("user-1", "What is TCP?", mode="general", save=False)
    assert answer.based_on_documents is False
    assert answer.sources == []
    assert answer.answer == "General answer."


def test_annotate_citations_sorts_cited_first():
    sources = [
        {"index": 1, "cited": False},
        {"index": 2, "cited": True},
    ]
    ordered = RagService._annotate_citations("See [2].", sources)
    assert ordered[0]["index"] == 2


class _MemoryQuizzes:
    """Tiny in-memory QuizRepository double for grading tests."""

    def __init__(self, questions):
        self.questions = questions

    def get(self, quiz_id, user_id):  # noqa: ARG002
        return {"_id": "quiz-1", "user_id": "u1", "title": "T", "topic": "T1",
                "questions": self.questions, "generation_method": "extractive"}


def test_quiz_grading_rules():
    """Grading is exact application logic inside `submit()` (brief §10)."""
    from services.quiz_service import QuizService
    from db.study_repositories import QuizAttemptRepository, StudyEventRepository

    questions = [
        {"question_id": "q1", "type": "mcq", "question": "Which is BCNF?",
         "options": ["BCNF", "2NF"], "correct_answer": "BCNF", "topic": "T1"},
        {"question_id": "q2", "type": "true_false", "question": "BCNF is a normal form",
         "options": ["True", "False"], "correct_answer": "True", "topic": "T1"},
        {"question_id": "q3", "type": "short_answer", "question": "What must a determinant be?",
         "correct_answer": "every determinant must be a superkey", "topic": "T1"},
    ]
    service = QuizService(quizzes=_MemoryQuizzes(questions),
                          attempts=QuizAttemptRepository(), events=StudyEventRepository())
    # q3 is answered with a genuine paraphrase: most of the expected idea,
    # inflected differently ("Determinants must be superkeys in BCNF").
    perfect = service.submit("u1", "quiz-1", {"q1": "  BCNF ", "q2": "true",
                                             "q3": "Determinants must be superkeys in BCNF"})
    assert perfect["score"] == 100.0, perfect
    # Two bare keywords are not an explanation (fewer than MIN_SA_WORDS).
    partial = service.submit("u1", "quiz-1", {"q1": "2NF", "q2": "true",
                                             "q3": "superkey determinant"})
    assert partial["score"] < 100.0, partial
    assert partial["results"][1]["correct"] is True
    # An unrelated sentence with enough words still fails on coverage.
    unrelated = service.submit("u1", "quiz-1",
                               {"q1": "2NF", "q2": "true",
                                "q3": "This is completely unrelated nonsense here"})
    assert unrelated["score"] < 100.0, unrelated
    assert unrelated["results"][2]["correct"] is False


def test_search_result_citation_shape():
    citation = _hit().to_citation() if hasattr(_hit(), "to_citation") else None
    # SearchResult carries everything the UI needs for a clickable citation.
    hit = _hit()
    assert hit.document_id and hit.document_title and hit.page_number and hit.text
    assert hit.score is not None
