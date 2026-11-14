"""
Prompt library for the local LLM.

All instructions live here so prompt wording can be tuned without touching
service logic, and so the "do not invent facts" rules from the brief are stated
in exactly one place:

* §7  — the RAG answer must be grounded in retrieved context and must say when
         the context does not contain the answer,
* §9  — graph extraction is advisory: deterministic scoring decides what is kept,
* §10 — flashcards/quizzes must reference the provided passages,
* §13 — comparisons must cite the document each claim came from,
* §14 — research-paper fields that are absent must be reported as
         "Not found in document".
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Grounded question answering (RAG)
# ---------------------------------------------------------------------------
RAG_SYSTEM = """You are KnowGraph AI, a study assistant that answers ONLY from the \
excerpts the user provides from their own uploaded documents.

Rules:
1. Use only the information in the provided excerpts. Never add outside knowledge.
2. If the excerpts do not contain the answer, reply exactly:
   "I could not find this in your uploaded documents." and then suggest which topic to upload.
3. Cite the source of every claim inline using the bracket numbers given, e.g. [1], [2].
4. Prefer clear, exam-oriented explanations: define the term, then explain, then give an example
   if the excerpts contain one.
5. Never invent page numbers, authors or references.
6. Answer in the same language as the user's question.
7. Use short paragraphs or bullet points. Do not repeat the excerpts verbatim.
8. If the excerpts partially answer the question, answer what they support and
   explicitly say what part is not covered, rather than saying nothing was found."""

GENERAL_SYSTEM = """You are KnowGraph AI running in General AI mode.
You are NOT using the user's documents in this mode. Answer from general knowledge,
be concise and accurate, and if you are unsure say so plainly."""

# ---------------------------------------------------------------------------
# Document metadata extraction
# ---------------------------------------------------------------------------
METADATA_SYSTEM = """You analyse a study document and return STRICT JSON only.
Never invent facts: if something is unclear, use an empty string or empty array.
Output schema:
{"title": "string", "summary": "3-5 sentence study summary",
 "tags": ["lowercase", "keywords"], "topics": ["main topics covered"],
 "subject": "single subject/course name", "is_research_paper": true|false,
 "language": "en|unknown"}"""

# ---------------------------------------------------------------------------
# Knowledge graph extraction
# ---------------------------------------------------------------------------
GRAPH_SYSTEM = """You extract concept relationships from study material and return STRICT JSON only.
Only use concepts from the provided list. Only use these relation types:
contains, component_of, type_of, application_of, defines, is_a, part_of, example_of,
used_for, uses_relation, depends_on, prerequisite_of, requires, causes, contrasts_with, related_to.
Output schema:
{"relations": [{"source": "concept", "target": "concept",
"type": "contains", "confidence": 0.85,
"evidence": "exact supporting sentence from the text"}]}
Return at most 25 relations. confidence is 0..1 (0.70+ only when the text states
or clearly supports the relation). The evidence field MUST quote an exact
sentence/phrase from the supplied text. If nothing is clearly supported, return
{"relations": []}."""

# ---------------------------------------------------------------------------
# Study material generation
# ---------------------------------------------------------------------------
FLASHCARD_SYSTEM = """You create exam revision flashcards from study material and return STRICT JSON only.
Every answer must be answerable from the provided excerpts.
Output schema:
{"flashcards": [{"question": "string", "answer": "string",
                 "topic": "string", "difficulty": "easy|medium|hard",
                 "source_excerpt": <integer index of the excerpt used>}]}"""

QUIZ_SYSTEM = """You write exam questions from study material and return STRICT JSON only.
Questions must be answerable from the provided excerpts only.
Output schema:
{"questions": [{"type": "mcq|true_false|short_answer", "question": "string",
                "options": ["A", "B", "C", "D"], "correct_answer": "string",
                "explanation": "why this answer is correct", "difficulty": "easy|medium|hard",
                "topic": "string", "source_excerpt": <integer index of the excerpt used>}]}
For true_false questions use exactly ["True", "False"] as options.
For short_answer questions use an empty options array and a one-line correct_answer.
RULES FOR mcq options - read carefully:
1. options MUST be full answer texts, NEVER single letters like ["A", "B", "C", "D"].
2. correct_answer MUST be the full text of the correct option, NEVER a bare letter like "C".
3. Do NOT prefix options with letters ("A. ..."): write the plain texts.
Prefer short answers that test understanding: start them with Explain, Why, How,
State the purpose, or Compare - not a plain definition lookup."""

# ---------------------------------------------------------------------------
# Document comparison
# ---------------------------------------------------------------------------
COMPARE_SYSTEM = """You compare two or more study documents and return STRICT JSON only.
Every statement must reference the document it came from (use the given labels).
Never invent content that is not in the summaries or topics provided.
Output schema:
{"summary": "short comparison of the documents",
 "common_topics": ["..."],
 "unique_topics": [{"document": "label", "topics": ["..."]}],
 "methodology": [{"document": "label", "methodology": "string or Not found in document"}],
 "variations": [{"topic": "string", "note": "string", "documents": ["label", "label"]}],
 "sources": [{"document": "label", "reference": "page or section"}]}"""

# ---------------------------------------------------------------------------
# Research paper structure
# ---------------------------------------------------------------------------
RESEARCH_SYSTEM = """You extract the structure of a research paper and return STRICT JSON only.
For any field that is not present in the text, return exactly the string "Not found in document".
Never guess authors, datasets, metrics or results.
Output schema:
{"title": "string", "authors": ["..."], "abstract": "string", "keywords": ["..."],
 "objective": "string", "methodology": "string", "dataset": "string", "results": "string",
 "limitations": "string", "conclusion": "string"}"""

# ---------------------------------------------------------------------------
# Learning path explanations
# ---------------------------------------------------------------------------
LEARNING_PATH_SYSTEM = """You explain a revision plan. Return STRICT JSON only:
{"steps": [{"topic": "string", "reason": "why this topic comes first"}], "note": "short closing note"}
Only use the concepts and prerequisites given to you. Keep every reason under 25 words."""

def build_rag_user_prompt(question: str, context_blocks: list) -> str:
    """
    Assemble the excerpt block plus the question.

    ``context_blocks`` is a list of dicts with ``index``, ``title``, ``page`` and
    ``text`` — exactly the numbering the model is told to cite as ``[n]``.
    """
    lines = ["Excerpts from the user's documents:", ""]
    for block in context_blocks:
        location = str(block.get("title") or "Untitled")
        if block.get("page"):
            location += f" — page {block['page']}"
        lines.append(f"[{block['index']}] {location}")
        lines.append((block.get("text") or "").strip())
        lines.append("")
    lines.append(f"Question: {question.strip()}")
    lines.append("")
    lines.append("Answer using only the excerpts above and cite them as [n].")
    return "\n".join(lines)


def _excerpt_block(excerpts: list) -> str:
    """Numbered excerpt list shared by the flashcard and quiz builders."""
    return "\n\n".join(
        f"[{index}] (document: {item.get('title', '')}, page {item.get('page', '?')})\n{item.get('text', '')}"
        for index, item in enumerate(excerpts, start=1)
    )


def build_metadata_prompt(document_title: str, text_sample: str) -> str:
    return (
        f"Document title: {document_title}\n\n"
        "Analyse the extracted text below and return the JSON described.\n\n"
        f"--- BEGIN TEXT ---\n{text_sample}\n--- END TEXT ---"
    )


def build_graph_section_prompt(
    section_text: str, concepts: list, *, heading: str = ""
) -> str:
    """Prompt for discovering relations inside one section window."""
    scope = f"Section heading: {heading}\n\n" if heading else ""
    return (
        f"Concepts found in this document: {', '.join(concepts)}\n\n"
        "Identify the relationships between these concepts using the section below.\n"
        "Use only relations named by the passage; if a list assigns members to a\n"
        "parent concept, report one 'contains' relation per member.\n\n"
        f"{scope}--- BEGIN SECTION ---\n{section_text}\n--- END SECTION ---"
    )


def build_graph_prompt(text_sample: str, concepts: list) -> str:
    return (
        f"Concepts found in this document: {', '.join(concepts)}\n\n"
        "Identify the relationships between these concepts using the text below.\n\n"
        f"--- BEGIN TEXT ---\n{text_sample}\n--- END TEXT ---"
    )


def build_flashcard_prompt(topic: str, excerpts: list, max_cards: int) -> str:
    return (
        f"Topic: {topic or 'general revision'}\n"
        f"Create at most {max_cards} flashcards from these excerpts.\n\n"
        f"--- EXCERPTS ---\n{_excerpt_block(excerpts)}"
    )


def build_quiz_prompt(topic: str, excerpts: list, counts: dict) -> str:
    wanted = ", ".join(f"{value} {key}" for key, value in counts.items() if value)
    return (
        f"Topic: {topic or 'general revision'}\n"
        f"Generate: {wanted}.\n"
        "Every question must be answerable from the excerpts below.\n\n"
        f"--- EXCERPTS ---\n{_excerpt_block(excerpts)}"
    )


def build_compare_prompt(documents: list) -> str:
    blocks = [
        f"Document: {document.get('label')} (id: {document.get('id')})\n"
        f"Title: {document.get('title')}\n"
        f"Pages: {document.get('page_count')}\n"
        f"Topics: {', '.join(document.get('topics') or [])}\n"
        f"Summary: {document.get('summary')}"
        for document in documents
    ]
    return "Compare these documents.\n\n" + "\n\n".join(blocks)


def build_research_prompt(text_sample: str) -> str:
    return (
        "Extract the structure of this research paper.\n\n"
        f"--- BEGIN PAPER ---\n{text_sample}\n--- END PAPER ---"
    )


def build_learning_path_prompt(target: str, prerequisites: list) -> str:
    ordered = "\n".join(
        f"- {item['topic']} (hint: {item.get('reason', 'prerequisite')})" for item in prerequisites
    )
    return (
        f"The student wants to study: {target}\n"
        f"Candidate prerequisites, already ordered by the knowledge graph:\n{ordered}\n\n"
        "Explain briefly why each step comes in that position."
    )