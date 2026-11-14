"""
Deterministic concept extraction for the knowledge graph (brief §9).

The brief explicitly says *not* to rely entirely on the LLM for the graph. This
module does the heavy lifting with classical techniques:

1. **Candidate generation** — capitalised phrases ("Functional Dependency"),
   acronyms ("BCNF", "TCP"), and frequent multi-word terms built from *consecutive*
   words of the text (stopwords included, so a phrase can never be assembled from
   words that were not actually adjacent).
2. **Scoring** — a TF-IDF-flavoured score: term frequency damped by document
   length, boosted for acronyms/definitions and for phrases that repeat. This is a
   *lexical* score, and the UI presents it as "importance in the text", never as an
   "AI confidence".
3. **Quality gates** — the score alone is not enough to become a node. Running
   headers/footers are removed, case variants are merged ("hill climbing" and
   "Hill Climbing" are one concept, not two), shouted ordinary words are rejected
   ("TOP", "HALF", "GREEDY", "THE" are typography, not acronyms), a capitalised
   phrase must also appear in running text, and fragments contained in a longer
   phrase are dropped ("third normal" → "third normal form").
4. **Definition detection** — a sentence containing "X is/are/means ..." is stored
   as the concept definition, which gives the graph node real content.
5. **Cue-phrase relations** — phrases such as "requires", "builds on", "is a type
   of" produce typed edges (``requires``, ``prerequisite_of``, ``part_of``, ...).

Everything here is pure Python: no model download, no network, fully explainable.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from utils.text import (
    STOPWORDS,
    clean_concept_label,
    normalize_for_match,
    normalize_whitespace,
    raw_words,
    reflow_lines,
    slugify,
    split_sentences,
)
# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
# Capitalised multi-word phrase: "Functional Dependency", "Normal Forms".
# The lookarounds stop a match from starting or ending *inside* a hyphenated compound:
# "Random-Restart Hill Climbing" must yield "Hill Climbing", never "Restart Hill Climbing".
_CAPITAL_PHRASE = re.compile(
    r"(?<![A-Za-z\-])(?:[A-Z][a-z]{1,}\s+){1,3}[A-Z][a-z]{1,}(?![A-Za-z\-])"
)
# Acronym: BCNF, TCP, DBMS, 3NF (starts with a digit).
_ACRONYM = re.compile(r"\b(?:[A-Z]{2,6}|\d[A-Z]{1,4})\b")
# Sentence patterns that usually define a term.
_DEFINITION_PATTERNS = (
    re.compile(r"^(?P<term>[\w\s\-]{3,60}?)\s+(?:is|are)\s+(?:a|an|the)?\s*(?P<body>.{20,300})$",
               re.IGNORECASE),
    re.compile(r"^(?P<term>[\w\s\-]{3,60}?)\s+means\s+(?P<body>.{15,300})$", re.IGNORECASE),
    re.compile(r"^(?P<term>[\w\s\-]{3,60}?)\s+refers to\s+(?P<body>.{15,300})$", re.IGNORECASE),
)
# A definition often sits mid-sentence ("Unlike search, Hill Climbing is ..."), so the
# verb is also searched for anywhere; the words just before it must be the label.
_MEDIAL_DEFINITION = re.compile(
    r"\b(?:is|are|means|refers to|is defined as|is known as)\b", re.IGNORECASE
)
# Sentence length (in words) above which a line counts as *running text* rather than
# a heading, a table row or a footer.
_PROSE_WORDS = 6
# Word-shaped tokens, used to spot a word the document also writes in normal case.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']{1,}")
# Lines that make a capitalised phrase a heading rather than a concept.
_NOISE_WORDS = {
    "page", "chapter", "figure", "table", "unit", "module", "contents", "index",
    "references", "abstract", "introduction", "conclusion", "example", "answer",
    "question", "exercise", "note", "notes", "summary", "objective", "objectives",
    "lecture", "assignment", "week", "date", "marks", "total",
}

# All-caps words that are ordinary English words, not acronyms. Slides and OCR shout
# table headers and emphasis ("TOP HALF Speed Completeness Memory", "GREEDY"), and the
# acronym pattern would otherwise publish "TOP", "HALF", "THE" as concepts. Deliberately
# excludes words that can legitimately *be* acronyms in a technical document
# (KEY, SET, MAP, TYPE, TIME, DATA, CODE, NODE, PATH, ...): those are only rejected when
# the document also writes them in normal case, which is checked separately.
_SHOUTED_ORDINARY = frozenset(
    """
    the and for with not you are but any out use new how why who its has was were will
    top bottom left right middle centre center half full upper lower inner outer front
    back next previous first second third fourth fifth last more most less least
    high low big small long short fast slow good bad best worst greedy
    old real true false yes plus minus
    also only even very just still yet never always often sometimes
    here there then now than that this these those they them their our your my we us he she it
    do does did done be been being am is are have had because since until
    about across against between through during without within along around above below
    under over inside outside before after while when where which what
    """.split()
)

# Cue phrases → relation type. Ordered from most specific to most generic.
_CUE_PATTERNS: Tuple[Tuple[re.Pattern, str, bool], ...] = (
    (re.compile(r"\bbuilt on\b|\bbuilds on\b|\bbased on\b|\bextends\b|\bprerequisite\b|\bbefore\s+\w+ing\b",
                re.IGNORECASE), "prerequisite_of", True),
    (re.compile(r"\brequires?\b|\bneeds\b", re.IGNORECASE), "requires", False),
    (re.compile(r"\bdepends on\b|\bdependent on\b|\brelies on\b", re.IGNORECASE), "depends_on", False),
    (re.compile(r"\bcauses?\b|\bleads to\b|\bresults in\b|\bproduces\b", re.IGNORECASE), "causes", False),
    # Structural containment verbs ("soft computing includes X").
    (re.compile(r"\bincludes?\b|\bincluding\b|\bcontains?\b|\bcontaining\b|\bcomprises?\b|\bconsists of\b"
                r"|\bcomposed of\b|\bmade up of\b|\bincorporates?\b", re.IGNORECASE), "contains", False),
    (re.compile(r"\bcomponents of\b|\bcomponent of\b|\bparts of\b|\belements of\b", re.IGNORECASE),
     "component_of", True),
    (re.compile(r"\btypes of\b|\btype of\b|\bkinds of\b|\bkind of\b|\bcategories of\b|\bcategory of\b|\bforms of\b",
                re.IGNORECASE), "type_of", False),
    (re.compile(r"\bapplications of\b|\bapplication of\b|\bapplied to\b|\bused in\b|\ban application of\b", re.IGNORECASE),
     "application_of", False),
    (re.compile(r"\bdefines?\b|\bdefined as\b|\brefers to\b|\bmeans\b", re.IGNORECASE), "defines", False),
    (re.compile(r"\bis\s+(?:a\s+)?(?:type|kind|form|subset|special case)\s+of\b|\bis\s+part\s+of\b",
                re.IGNORECASE), "part_of", False),
    (re.compile(r"\bis\s+an?\s+(?:\w+\s+){0,2}(?:algorithm|method|technique|approach|model|protocol|structure)\b",
                re.IGNORECASE), "is_a", False),
    (re.compile(r"\bis an example of\b|\bfor example\b|\be\.g\.\b|\bsuch as\b", re.IGNORECASE),
     "example_of", False),
    (re.compile(r"\bused for\b|\bused to\b|\benables\b|\ballows\b", re.IGNORECASE), "used_for", False),
    (re.compile(r"\buses the\b\s*(?:\w+\s+){0,2}relation\b|\buses\b.{0,40}\brelation\b", re.IGNORECASE),
     "uses_relation", False),
    (re.compile(r"\bdiffers from\b|\bdifferent from\b|\bin contrast\b|\bunlike\b|\bwhereas\b|\bcompared to\b",
                re.IGNORECASE), "contrasts_with", False),
    (re.compile(r"\bexplains\b|\bexplained by\b|\bdetermines\b", re.IGNORECASE),
     "explains", False),
)


@dataclass
class ConceptCandidate:
    """A concept found in a document, with the evidence needed for the graph."""

    label: str
    slug: str
    score: float = 0.0
    occurrences: int = 0
    pages: List[int] = field(default_factory=list)
    snippets: List[str] = field(default_factory=list)
    definition: str = ""
    kind: str = "phrase"          # phrase | acronym | term

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "slug": self.slug,
            "score": round(self.score, 4),
            "occurrences": self.occurrences,
            "pages": self.pages,
            "definition": self.definition,
            "kind": self.kind,
        }


@dataclass
class RelationCandidate:
    """A typed relationship between two concept labels."""

    source: str
    target: str
    relation: str
    method: str = "cooccurrence"
    weight: float = 1.0
    page_number: Optional[int] = None
    snippet: str = ""
    chunk_id: str = ""
    evidence_count: int = 1
    confidence: Optional[float] = None
    verification_status: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "method": self.method,
            "weight": round(self.weight, 3),
            "page_number": self.page_number,
            "snippet": self.snippet,
            "chunk_id": self.chunk_id,
            "evidence_count": self.evidence_count,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
        }

    def evidence_payload(self) -> Dict[str, Any]:
        """Shape written into the relation document's evidence array."""
        from models.graph import default_relation_confidence, verification_for_method

        confidence = (
            self.confidence
            if self.confidence is not None
            else default_relation_confidence(
                self.method, [{"snippet": self.snippet}] if self.snippet else []
            )
        )
        return {
            "page_number": self.page_number,
            "snippet": self.snippet,
            "chunk_id": self.chunk_id,
            "method": self.method,
            "confidence": round(float(confidence), 2),
            "verification_status": (
                self.verification_status or verification_for_method(self.method)
            ),
            "evidence_count": max(1, int(self.evidence_count)),
        }


# Structural headings: "Components of X" -> component_of (X contains each listed concept).
_SECTION_HEADER_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"^components?\s+of\s+(?P<parent>.{2,80})$", re.IGNORECASE), "component_of"),
    (re.compile(r"^types?\s+of\s+(?P<parent>.{2,80})$", re.IGNORECASE), "type_of"),
    (re.compile(r"^applications?\s+of\s+(?P<parent>.{2,80})$", re.IGNORECASE), "application_of"),
    (re.compile(r"^parts?\s+of\s+(?P<parent>.{2,80})$", re.IGNORECASE), "component_of"),
)

_LIST_ITEM = re.compile(r"^\s*(?:[-•*▪◦►–—]|\d{1,3}[.)\-:]|[a-zA-Z][.)])\s+(?P<body>.{2,300})$")

_KNOWN_ALL_CAPS_HEADINGS = frozenset()

#: Sentence splitter shared with text helpers — long lines are prose.
_END_OF_SENTENCE = re.compile(r"[.!?]\s*$")


def split_into_sections(
    pages: Sequence[Tuple[int, str]],
) -> List[Dict[str, Any]]:
    """
    Rebuild *section context* from pages: short lines become headings for the
    paragraphs/lists that follow them; numbering/bullets mark list items.
    Returns dicts with page_number, heading, text, kind ("heading" not stored).
    """
    sections: List[Dict[str, Any]] = []
    pending_heading = ""

    for page_number, raw_text in pages:
        for line in (raw_text or "").split("\n"):
            text = line.strip()
            if not text:
                continue
            list_match = _LIST_ITEM.match(text)
            if list_match:
                sections.append({
                    "page_number": page_number,
                    "heading": pending_heading,
                    "text": list_match.group("body").strip(),
                    "kind": "list",
                })
                continue
            words = raw_words(text)
            if (
                len(words) <= 12
                and not re.search(r"[.!?]\s+[A-Z0-9\"'(\[]", text)
                and not _END_OF_SENTENCE.search(text)
            ):
                pending_heading = text
                continue
            sections.append({
                "page_number": page_number,
                "heading": pending_heading,
                "text": text,
                "kind": "paragraph",
            })
    return sections


# ---------------------------------------------------------------------------
# Text preparation
# ---------------------------------------------------------------------------
def _line_key(line: str) -> str:
    """Line form for repeat detection; case/punctuation-insensitive."""
    return re.sub(r"[^a-z0-9]+", " ", (line or "").lower()).strip()


def _strip_leading_articles(text: str) -> str:
    lowered = (text or "").strip().lower()
    for article in ("the ", "a ", "an "):
        if lowered.startswith(article) and len(text) > len(article) + 2:
            return text[len(article):].strip()
    return (text or "").strip()


def _member_hits(tail: str, by_label: Dict[str, ConceptCandidate]) -> List[ConceptCandidate]:
    """Concepts mentioned in a list tail — longest label match wins per span."""
    lowered = (tail or "").lower()
    hits: List[ConceptCandidate] = []
    seen_spans: List[Tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < stop and end > begin for begin, stop in seen_spans)

    ordered = sorted(by_label.values(), key=lambda c: len(c.label), reverse=True)
    for candidate in ordered:
        name = candidate.label.lower()
        if len(name) < 3:
            continue
        start = lowered.find(name)
        if start == -1:
            continue
        before = lowered[start - 1] if start > 0 else " "
        after = lowered[start + len(name)] if start + len(name) < len(lowered) else " "
        if before.isalnum() or after.isalnum():
            continue
        if overlaps(start, start + len(name)):
            continue
        seen_spans.append((start, start + len(name)))
        hits.append(candidate)
    return hits


def _resolve_parent(heading: str, by_label: Dict[str, ConceptCandidate]) -> Optional[ConceptCandidate]:
    direct = by_label.get(normalize_for_match(heading.strip(" -–—:;")))
    if direct:
        return direct
    for pattern, _ in _SECTION_HEADER_PATTERNS:
        match = pattern.match(heading.strip())
        if match:
            holder = by_label.get(normalize_for_match(match.group("parent")))
            if holder:
                return holder
    candidate = _strip_leading_articles(heading)
    return by_label.get(normalize_for_match(candidate.strip(" -–—:;")))


def _header_relation(heading: str) -> str:
    for pattern, rel_type in _SECTION_HEADER_PATTERNS:
        if pattern.match(heading.strip()):
            return rel_type
    lowered_head = normalize_whitespace(heading.lower())
    if re.search(r"\btypes?|kinds?|categories?|forms?\b", lowered_head):
        return "type_of"
    if re.search(r"\bapplications?\b", lowered_head):
        return "application_of"
    return "component_of"


_PARENT_USES = re.compile(
    r"^(?P<parent>.{2,80}?)\s+uses?\s+(?P<tail>.{2,400})$", re.IGNORECASE)


def _parent_uses_pattern(text: str) -> Optional[Tuple[str, str, str]]:
    """'<Parent> uses <members>' fan-out inside one short sentence."""
    if len(raw_words(text)) > 40:
        return None
    match = _PARENT_USES.match(text.strip())
    if not match:
        return None
    parent = match.group("parent").strip()
    tail = match.group("tail").strip()
    if re.search(r"\brelation\b", tail, re.IGNORECASE):
        return (parent, "uses_relation", tail)
    return None


def extract_structural_relations(
    sections: Sequence[Dict[str, Any]],
    concepts: Sequence[ConceptCandidate],
    *,
    max_relations_per_parent: int = 12,
) -> List[RelationCandidate]:
    """
    Infer containment relations from document structure:

    * ``<heading>: <ConceptA>, <ConceptB>`` inline fan-out ("Types of X: A, B"),
    * a structural header ("Components of X") followed by concept-only lines,
    * a heading line itself naming the parent with concept-only lines after it,
    * a short sentence "<Parent> uses <A>, <B> relations" fan-out.

    Every result carries heading + line text as evidence (``method =
    structural``) — invented members are impossible because a line links only
    when it names exactly an extracted concept.
    """
    by_label = {normalize_for_match(c.label): c for c in concepts}
    produced: Dict[Tuple[str, str, str], RelationCandidate] = {}

    def emit(parent_label: str, parent_slug: str, child: ConceptCandidate,
             relation: str, evidence: str, page_number: Optional[int],
             heading: str = "") -> None:
        key = (parent_slug, child.slug, relation)
        if key in produced or parent_slug == child.slug:
            return
        snippet = (heading + ": " + evidence).strip(": ")[:280] if heading else evidence[:280]
        produced[key] = RelationCandidate(
            source=parent_label,
            target=child.label,
            relation=relation,
            method="structural",
            weight=1.2,
            page_number=page_number,
            snippet=snippet,
        )

    for section in sections:
        kind = section.get("kind", "paragraph")
        heading = (section.get("heading") or "").strip()
        text = (section.get("text") or "").strip()
        page_number = section.get("page_number")
        if not text:
            continue

        # 1. Inline fan-out: "<head phrase>: A, B, C" -------------------------
        if ":" in text:
            head, _, tail = text.partition(":")
            parent_label = ""
            relation: Optional[str] = None
            for pattern, rel_type in _SECTION_HEADER_PATTERNS:
                match = pattern.match(head.strip())
                if match:
                    parent_label = match.group("parent").strip()
                    relation = rel_type
                    break
            if not relation:
                lowered_head = normalize_whitespace(head.strip().lower())
                if re.search(r"\b(components?|parts?|elements?)\b", lowered_head):
                    relation, parent_label = "component_of", _strip_leading_articles(head)
                elif re.search(r"\btypes?|kinds?|categories?|forms?\b", lowered_head):
                    relation, parent_label = "type_of", _strip_leading_articles(head)
                elif re.search(r"\bapplications?\b", lowered_head):
                    relation, parent_label = "application_of", _strip_leading_articles(head)
            if relation and parent_label and tail.strip():
                parent = by_label.get(normalize_for_match(parent_label.strip(" -–—:;")))
                if parent:
                    children = _member_hits(tail, by_label)
                    for child in children[:max_relations_per_parent]:
                        if child.slug != parent.slug:
                            emit(parent.label, parent.slug, child, relation,
                                 tail.strip(), page_number, head.strip())
                    continue

        # 2. List item naming exactly one concept under a structural header ----
        if kind == "list":
            members = _member_hits(text, by_label)
            if heading and len(members) == 1:
                parent = _resolve_parent(heading, by_label)
                if parent and members[0].slug != parent.slug:
                    emit(parent.label, parent.slug, members[0],
                         _header_relation(heading), text, page_number, heading)
                continue
            # 3. "<Parent> uses <A>, <B> relations" fan-out -------------------
            sentence = _parent_uses_pattern(text)
            if sentence:
                parent_name, rel_type, tail = sentence
                holder = by_label.get(normalize_for_match(parent_name))
                if holder:
                    kids = _member_hits(tail, by_label)[:max_relations_per_parent]
                    for child in kids:
                        if child.slug != holder.slug:
                            emit(holder.label, holder.slug, child,
                                 rel_type, text, page_number)
    return sorted(produced.values(), key=lambda item: item.weight, reverse=True)


def _edge_lines(text: str, count: int) -> List[str]:
    lines = [line.strip() for line in (text or "").split("\n") if line.strip()]
    return lines[:count] + lines[-count:]


def strip_running_boilerplate(
    pages: Sequence[Tuple[int, str]],
    *,
    edge_lines: int = 2,
    min_pages: int = 3,
    ratio: float = 0.6,
) -> List[Tuple[int, str]]:
    """
    Remove running headers/footers that repeat at the top or bottom of most pages.

    A PDF exported from a note-taking tool stamps the same footer on every page
    ("Gemini Notebook"), and that stamp was previously the *highest scoring
    "concept"* in the document. Only the first/last few lines of a page are
    considered, so a phrase that legitimately repeats in the body is untouched.
    """
    if len(pages) < min_pages:
        return list(pages)

    counts: Counter = Counter()
    for _page_number, text in pages:
        for line in _edge_lines(text, edge_lines):
            counts[_line_key(line)] += 1

    threshold = max(min_pages, int(len(pages) * ratio + 0.5))
    boilerplate = {key for key, count in counts.items() if key and count >= threshold}
    if not boilerplate:
        return list(pages)

    cleaned: List[Tuple[int, str]] = []
    for page_number, text in pages:
        kept = [line for line in (text or "").split("\n") if _line_key(line) not in boilerplate]
        cleaned.append((page_number, "\n".join(kept)))
    return cleaned


def prepare_graph_pages(pages: Sequence[Tuple[int, str]]) -> List[Tuple[int, str]]:
    """
    Normalise page text before graph extraction.

    Two fixes that both come from real PDF/slide exports: repeated running
    headers/footers are dropped (:func:`strip_running_boilerplate`), and hard-wrapped
    lines are reflowed so a definition or cue phrase split across two lines is seen
    as one sentence. Idempotent, so it is safe to call from more than one entry point.
    """
    cleaned = strip_running_boilerplate(pages)
    return [(number, reflow_lines(text)) for number, text in cleaned]


def _page_sentences(text: str) -> Iterator[str]:
    """
    Sentence-like units of a page: lines first, then sentences within each line.

    Lines come first because a slide/page is titled *and* written: without this, a
    heading and the paragraph under it end up in one "sentence", which made a
    five-word slide title look like running text.
    """
    for line in (text or "").split("\n"):
        for sentence in split_sentences(line):
            yield sentence


def _prose_blob(pages: Sequence[Tuple[int, str]]) -> str:
    """
    Lowercased running text: sentences long enough to be prose, not headings.

    Used as the "does this term actually appear in the text?" test without running a
    regex per candidate.
    """
    chunks: List[str] = []
    for _page_number, text in pages:
        for sentence in _page_sentences(text):
            if len(sentence.split()) >= _PROSE_WORDS:
                chunks.append(sentence.lower())
    return " \n ".join(chunks)


def _non_shouted_words(text: str) -> Counter:
    """
    Words the document also writes in normal case, with how often each occurs.

    If "greedy" appears anywhere lower/TITLE-CASED, then "GREEDY" is emphasis and not
    an acronym — a cheap, document-local substitute for a dictionary. Hyphenated words
    are split as well, so "state-space" vouches for "SPACE". A count (not just a
    set membership flag) is kept so a single stray mixed-case sighting of a *short*
    token ("Ai" instead of "AI", a one-off typo or OCR slip) doesn't get the same
    veto power as a word the document consistently writes in normal case.
    """
    counts: Counter = Counter()
    for match in _WORD_RE.finditer(text or ""):
        word = match.group(0)
        if word.isupper():
            continue
        counts[word.lower()] += 1
        for part in re.split(r"[-']", word):
            if part:
                counts[part.lower()] += 1
    return counts


def _is_shouted_word(label: str, ordinary_case_counts: Counter) -> bool:
    """True when an ALL-CAPS token is a shouted ordinary word rather than an acronym."""
    lowered = label.lower()
    if lowered in _SHOUTED_ORDINARY:
        return True
    # A short (<=3 char) acronym needs *repeated* normal-case sightings to be
    # disqualified — a lone "Ai" among hundreds of "AI"s is a typo, not evidence the
    # document treats it as an ordinary word. Longer tokens keep the original,
    # stricter one-sighting-is-enough rule.
    #
    # "ai"/"ml" are pronouns/prepositions of other languages ("ai" = "to the" in
    # Portuguese, "ml" = "millilitre" in ingredient lists), so a couple of
    # lowercase sightings cannot disqualify them: a genuine acronym is written
    # uppercase dozens of times, and that uppercase run is what counts.
    min_repeat = 2 if len(label) <= 3 else 1
    ordinary = ordinary_case_counts.get(lowered, 0)
    if len(label) <= 2 and ordinary <= 3:
        return False
    return ordinary >= min_repeat


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------
# Real, non-stopword English words that repeat often in any notes/textbook but carry
# no topical meaning by themselves ("new technologies", "for example", "in general").
# These pass every other gate — they're not stopwords, not shouted caps, and they
# genuinely repeat — so without this they show up as low-value nodes.
_GENERIC_FILLER_WORDS = frozenset(
    """
    new old good bad better best great important useful major minor various
    certain particular general specific different similar common simple basic
    main key overall real actual current final initial single multiple
    example examples instance case cases kind kinds sort sorts type types
    way ways thing things part parts point points area field level
    """.split()
)


_SUBFIELD_GENERICS = frozenset(
    """
    field
    fields
    area
    areas
    domain
    domains
    branch
    branches
    discipline
    disciplines
    """.split()
)


def _is_generic_filler(label: str) -> bool:
    """
    True when *every* content word in the label is generic filler rather than
    domain vocabulary — "For Example", "New Technologies", "Various Types" carry no
    meaning on their own even though they repeat and pass every other gate. A label
    with even one non-filler word (e.g. "Expert System") is left alone.

    Subfield names such as "Computer Science" are *not* filler: it is the parent
    discipline of exactly the topics in these notes (AI, ML, NLP, ...), and it is
    the hub that keeps definitional sentences connected in the graph ("Artificial
    Intelligence is composed of two words ... of computer science"). Without it,
    top-level terms stay isolated.
    """
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", label)]
    if not words:
        return True
    stripped = [w for w in words if w not in _SUBFIELD_GENERICS and w not in STOPWORDS]
    if not stripped:
        return True
    if stripped == ["computer", "science"]:
        return False
    return all(w in _GENERIC_FILLER_WORDS or w in STOPWORDS for w in words)


def _is_noise(label: str, *, kind: str = "term") -> bool:
    words = [word.lower() for word in re.findall(r"[A-Za-z]+", label)]
    if not words:
        return True
    if words[0] in _NOISE_WORDS:
        return True
    # Acronyms are already shape-validated by _ACRONYM ([A-Z]{2,6} or \d[A-Z]{1,4}),
    # so a 2-letter acronym (AI, ML, OS, UI, DB, VR, AR, IT, PC, ...) is real signal,
    # not junk. Phrases/terms keep the 3-char floor to reject stray fragments.
    # Keeping the acronyms as candidates also matters for relations: the
    # definition layer expands bare "ML"/"AI" mentions into their full labels,
    # so the acronym carries the definitional sentences its expansion needs.
    min_length = 2 if kind == "acronym" else 3
    if len(label) < min_length or len(label) > 70:
        return True
    return bool(re.search(r"[.!?]$", label.strip()))


def _heading_blob(pages: Sequence[Tuple[int, str]]) -> str:
    """
    Normalised text of every short, heading-shaped line, joined into one blob for
    cheap substring checks.

    A term that names the document's own title or a section heading ("INTRODUCTION
    TO ARTIFICIAL INTELLIGENCE") is the strongest available signal that it is the
    *main* concept — independent of body frequency. Without this, a broad topic term
    that is genuinely the subject of a long, multi-section document can still lose
    out to a narrower term that happens to repeat more densely in one section (e.g.
    "Expert System" out-scoring "Artificial Intelligence" in a full-syllabus PDF).
    """
    lines: List[str] = []
    for _page_number, text in pages:
        for line in (text or "").split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            words = raw_words(stripped)
            if len(words) <= 12 and not _END_OF_SENTENCE.search(stripped):
                lines.append(normalize_for_match(stripped))
    return "\n".join(lines)


_NOTATION_CONTEXT = re.compile(r"[\[\],]")


def _digit_acronym_notation_ratio(pages: Sequence[Tuple[int, str]]) -> Dict[str, float]:
    """
    For each digit-prefixed acronym match ("1B", "3M", "3NF", ...), the fraction of
    its sightings that sit right next to ``[`` ``]`` or ``,``.

    The digit-acronym branch of :data:`_ACRONYM` exists for genuine terms like
    "3NF" or "2D" — but it also matches compact state-tuple notation used in search
    problems ("[3M, 3C, 1B]" for 3 missionaries / 3 cannibals / 1 boat in the Water
    Jug / river-crossing family of problems). Those tokens overwhelmingly sit beside
    brackets and commas; a real acronym used in prose mostly doesn't. Only labels
    seen at least 3 times are scored, so a couple of incidental sightings can't flip
    the verdict either way.
    """
    hits: Counter = Counter()
    totals: Counter = Counter()
    for _page_number, text in pages:
        body = normalize_whitespace(text)
        for match in _ACRONYM.finditer(body):
            label = match.group(0)
            if not label[0].isdigit():
                continue
            totals[label] += 1
            context = body[max(0, match.start() - 3): match.start()] + body[match.end(): match.end() + 3]
            if _NOTATION_CONTEXT.search(context):
                hits[label] += 1
    return {label: hits[label] / totals[label] for label in totals if totals[label] >= 3}


def collect_candidates(
    pages: Sequence[Tuple[int, str]],
    *,
    max_concepts: int = 60,
    min_score: float = 0.08,
) -> List[ConceptCandidate]:
    """
    Find and score concept candidates across a document.

    ``pages`` is a sequence of ``(page_number, text)`` pairs, so every concept can
    point back to the page it was seen on. The text is normalised first (running
    headers/footers removed, hard-wrapped lines reflowed) — see
    :func:`prepare_graph_pages`.
    """
    pages = prepare_graph_pages(pages)

    counts: Counter = Counter()
    kinds: Dict[str, str] = {}
    pages_for: Dict[str, set] = defaultdict(set)
    total_tokens = 0

    # Words the document also writes in normal case, collected up front so the answer
    # does not depend on page order.
    ordinary_case_words: Counter = Counter()
    for _page_number, text in pages:
        ordinary_case_words += _non_shouted_words(text)

    notation_ratio = _digit_acronym_notation_ratio(pages)
    prose = _prose_blob(pages)

    for page_number, text in pages:
        if not text:
            continue
        body = normalize_whitespace(text)
        total_tokens += max(1, len(body.split()))

        for match in _ACRONYM.finditer(body):
            label = match.group(0).strip()
            if _is_noise(label, kind="acronym") or _is_shouted_word(label, ordinary_case_words):
                continue
            # Reject digit-acronym matches that are table/tuple shorthand ("1B", "3M"
            # from a Water Jug state vector) rather than a genuine term: real acronyms
            # essentially never sit next to brackets/commas on (almost) every sighting.
            if label[0].isdigit() and notation_ratio.get(label, 0.0) >= 0.7:
                continue
            counts[label] += 1
            kinds.setdefault(label, "acronym")
            pages_for[label].add(page_number)

        for match in _CAPITAL_PHRASE.finditer(body):
            label = clean_concept_label(match.group(0))
            if _is_noise(label) or _is_generic_filler(label):
                continue
            counts[label] += 1
            kinds.setdefault(label, "phrase")
            pages_for[label].add(page_number)

        # Frequent multi-word terms. Windows slide over *consecutive* words, stopwords
        # included, so a phrase can never be assembled from words that were not
        # adjacent in the text: filtering stopwords first is what turned a table of
        # "Job A Job B / Job E Job F" labels into the concept "job job".
        words = raw_words(body)
        for start in range(len(words) - 1):
            for size in (2, 3):
                window = words[start : start + size]
                if len(window) < size:
                    continue
                if any(token in STOPWORDS or len(token) < 3 for token in window):
                    continue
                if len(set(window)) < size:
                    continue  # "job job" is not a concept
                phrase = " ".join(window)
                if _is_noise(phrase) or _is_generic_filler(phrase):
                    continue
                counts[phrase] += 1
                kinds.setdefault(phrase, "term")
                pages_for[phrase].add(page_number)

    counts, kinds, pages_for, forms = _merge_case_variants(counts, kinds, pages_for)
    counts, kinds, pages_for = _merge_acronym_phrase_variants(counts, kinds, pages_for)
    headings = _heading_blob(pages)

    # The score is term frequency *per 1000 tokens*, so the same phrase in a
    # 136-page book scores far lower than in a two-page note. A fixed
    # ``min_score`` calibrated on small documents therefore emptied the graph for
    # long ones ("Artificial Intelligence" in a 136-page unit scored 0.055 < 0.08
    # and vanished). The threshold is relaxed proportionally to document length:
    # relative ordering is untouched, and genuinely rare junk (a phrase seen
    # twice in 35k words still scores ~0.004) is still rejected.
    token_scale = max(1.0, total_tokens / 6000)
    effective_min_score = max(0.012, min_score / token_scale)

    minimum_occurrences = 2
    candidates: List[ConceptCandidate] = []
    for label, count in counts.items():
        kind = kinds.get(label, "term")
        # Acronyms are meaningful even with a low count; phrases must repeat.
        if kind != "acronym" and count < minimum_occurrences:
            continue
        # A phrase that is also used by acronym genuinely shows its face less
        # often than its true frequency: notes introduce "Artificial
        # Intelligence" once and write "AI" (74 sightings) ever after. The merge
        # above already folded those sightings into the phrase's count, so the
        # score below reflects the concept's real frequency, not just its
        # spelled-out mentions.
        frequency = count / max(1, total_tokens / 1000)
        boost = {"acronym": 1.4, "phrase": 1.15, "term": 1.0}[kind]
        length_penalty = 1.0 if len(label.split()) == 1 else 1.0 / (len(label.split()) ** 0.35)
        heading_bonus = 1.6 if normalize_for_match(label) in headings else 1.0
        score = round(frequency * boost * length_penalty * heading_bonus / 10, 4)

        candidates.append(
            ConceptCandidate(
                label=label,
                slug=slugify(label),
                score=score,
                occurrences=count,
                pages=sorted(pages_for[label]),
                kind=kind,
            )
        )

    candidates.sort(key=lambda item: (item.score, item.occurrences), reverse=True)
    passing = [
        item
        for item in candidates
        if item.score >= effective_min_score
        and _is_concept_like(item, forms.get(item.label, []), prose, pages)
    ]
    filtered = _prune_subsumed(passing)[:max_concepts]

    for candidate in filtered:
        candidate.definition, snippet = find_definition(pages, candidate.label)
        candidate.snippets = [snippet] if snippet else []
    return filtered


# Ranked preference between the passes that can find the same concept.
_KIND_RANK = {"acronym": 3, "phrase": 2, "term": 1}


def _case_quality(label: str) -> int:
    """1 when a label keeps real capitalisation, 0 when it is all lowercase."""
    return 1 if any(char.isupper() for char in label) else 0


def _merge_case_variants(
    counts: Counter,
    kinds: Dict[str, str],
    pages_for: Dict[str, set],
) -> Tuple[Counter, Dict[str, str], Dict[str, set], Dict[str, List[str]]]:
    """
    Collapse case variants of one concept into a single candidate.

    The n-gram pass works in lowercase while the phrase pass keeps the original
    casing, so "hill climbing" and "Hill Climbing" were published as two separate
    nodes — the same concept twice in the graph. The best-cased, strongest form
    wins, pages are unioned, and the occurrence count is the **largest** of the
    variants (they describe the same occurrences, so summing would inflate it).
    """
    grouped: Dict[str, List[str]] = defaultdict(list)
    for label in counts:
        grouped[normalize_for_match(label)].append(label)

    merged_counts: Counter = Counter()
    merged_kinds: Dict[str, str] = {}
    merged_pages: Dict[str, set] = {}
    forms: Dict[str, List[str]] = {}

    for variants in grouped.values():
        display = max(
            variants,
            key=lambda label: (_KIND_RANK.get(kinds.get(label, "term"), 1), _case_quality(label)),
        )
        merged_counts[display] = max(counts[label] for label in variants)
        merged_kinds[display] = kinds.get(display, "term")
        merged_pages[display] = set().union(*(pages_for[label] for label in variants))
        forms[display] = list(variants)

    return merged_counts, merged_kinds, merged_pages, forms


def _initials(phrase: str) -> str:
    """'Artificial Intelligence' -> 'AI'."""
    return "".join(word[0].upper() for word in re.findall(r"[A-Za-z]+", phrase))


def _merge_acronym_phrase_variants(
    counts: Counter,
    kinds: Dict[str, str],
    pages_for: Dict[str, set],
) -> Tuple[Counter, Dict[str, str], Dict[str, set]]:
    """
    Fold a short acronym into the multi-word phrase it stands for, when the phrase's
    initials match the acronym exactly ("Artificial Intelligence" absorbs "AI").

    Without this, notes that use both forms (very common — "AI" appears far more
    often than the spelled-out phrase once it has been introduced) split one concept
    into two half-strength candidates, and the real central concept never becomes the
    graph's biggest hub. The longer phrase is kept as the canonical, readable label;
    occurrences and pages of the acronym are folded in rather than summed against a
    threshold, since they are genuinely separate mentions of the same concept.
    """
    phrase_by_initials: Dict[str, List[str]] = defaultdict(list)
    for label, kind in kinds.items():
        if kind == "phrase" and len(label.split()) >= 2:
            phrase_by_initials[_initials(label)].append(label)

    acronym_labels = [label for label, kind in kinds.items() if kind == "acronym"]
    if not acronym_labels or not phrase_by_initials:
        return counts, kinds, pages_for

    merged_counts = Counter(counts)
    merged_kinds = dict(kinds)
    merged_pages = {label: set(members) for label, members in pages_for.items()}

    for acronym_label in acronym_labels:
        matches = phrase_by_initials.get(acronym_label.upper())
        if not matches or acronym_label not in merged_counts:
            continue
        # A digit-leading "acronym" is usually table/tuple shorthand ("3M", "1B"
        # from a Water Jug state vector), not a term — only fold when the
        # acronym genuinely reads as the phrase's initials in running prose.
        if acronym_label[0].isdigit():
            continue
        # Prefer the longest (most explicit) phrase form; a higher count breaks
        # ties. A two-letter abbreviation is *always* folded into its phrase
        # ("AI" → "Artificial Intelligence", "ML" → "Machine Learning"): such a
        # token is never a word of its own, so keeping it as a separate node
        # would split one concept into two disconnected halves — the graph would
        # show the abbreviation without the concept, exactly what happened to AI.
        canonical = max(
            matches,
            key=lambda p: (len(p), merged_counts.get(p, 0))
            if len(acronym_label) <= 2
            else (merged_counts.get(p, 0), len(p)),
        )
        merged_counts[canonical] = merged_counts.get(canonical, 0) + merged_counts.pop(acronym_label)
        merged_pages[canonical] = merged_pages.get(canonical, set()) | merged_pages.pop(acronym_label, set())
        merged_kinds.pop(acronym_label, None)
        merged_kinds[canonical] = "phrase"

    return merged_counts, merged_kinds, merged_pages


def _is_concept_like(
    candidate: ConceptCandidate,
    forms: Sequence[str],
    prose: str,
    pages: Sequence[Tuple[int, str]],
) -> bool:
    """
    Final quality gate: the score is not enough, the *shape* has to be right.

    * A **capitalised phrase** must also appear in running text. A slide title or a
      page footer is typography, not a concept ("The Upgrade", "Gemini Notebook").
      Three mentions are accepted even without prose, so a term that only shows up
      in headings and diagrams is not lost.
    * An **all-caps token** is checked against the document's own vocabulary while it
      is collected (:func:`_is_shouted_word`); here a one-off fragment that never
      appears in running text is dropped, while digit-bearing names (3NF) always pass.
    """
    if candidate.kind == "phrase":
        if candidate.occurrences < 3 and _is_heading_label(candidate.label, pages):
            return False
        if candidate.occurrences >= 3:
            return True
        return any(form.lower() in prose for form in forms)
    if candidate.kind == "acronym":
        if any(char.isdigit() for char in candidate.label):
            return True
        return candidate.occurrences >= 2 or candidate.label.lower() in prose
    return True


def _word_bounded(label: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z])" + re.escape(label) + r"(?![A-Za-z])", re.IGNORECASE)


def _is_heading_label(label: str, pages: Sequence[Tuple[int, str]]) -> bool:
    """
    True when *every* mention of the phrase is a label immediately followed by a colon.

    "The Upgrade: Random-Restart Hill Climbing" is the *title of a section*, not a
    concept the notes explain — the phrase is a caption for the line beneath it. Used
    only for low-frequency phrases, so a term that is genuinely repeated (and may well
    appear in headings too) is not thrown away. The word "upgrade" does occur in the
    prose of these notes, which is why a plain "does this text appear?" test kept it.
    """
    pattern = _word_bounded(label)
    seen = 0
    for _page_number, text in pages:
        for line in (text or "").split("\n"):
            for match in pattern.finditer(line):
                seen += 1
                if line[match.end() :].lstrip()[:1] != ":":
                    return False
    return seen > 0


def _prune_subsumed(candidates: Sequence[ConceptCandidate]) -> List[ConceptCandidate]:
    """
    Drop n-gram fragments contained in a longer, at-least-as-frequent phrase.

    "third normal form" and its fragment "third normal" are the same concept, and
    only the complete phrase should become a node. Comparing frequencies keeps a
    genuinely common short phrase ("normal form", used everywhere) alive.
    """
    kept: List[ConceptCandidate] = []
    for candidate in candidates:
        if candidate.kind == "term" and any(
            other is not candidate
            and other.kind in ("term", "phrase")
            and other.occurrences >= candidate.occurrences
            and _word_bounded(candidate.label).search(other.label)
            for other in candidates
        ):
            continue
        kept.append(candidate)
    return kept


def _clean_sentence(sentence: str) -> str:
    """Single-line, whitespace-normalised sentence (snippets are shown in the UI)."""
    return normalize_whitespace(sentence or "").replace("\n", " ").strip()


def _term_matches(term: str, target: str) -> bool:
    """Does the words before the verb actually name the concept?"""
    value = normalize_for_match(clean_concept_label(term))
    if not value or not target:
        return False
    return value == target or value.endswith(" " + target) or target.endswith(" " + value)


def _definition_sentence(unit: str, target: str) -> str:
    """
    The sentence itself when it defines ``target``, otherwise an empty string.

    Two shapes are accepted: the term at the start of the sentence ("BCNF is a
    normal form where ..."), and the term immediately before the verb anywhere in
    the sentence ("Unless a superkey holds, BCNF is not satisfied"). The second
    shape matters because explanation-heavy notes rarely start a sentence with the
    term they are defining — the old code only ever tried the first shape.
    """
    for pattern in _DEFINITION_PATTERNS:
        match = pattern.match(unit)
        if match and _term_matches(match.group("term"), target) and len(match.group("body").strip()) >= 20:
            return unit

    for match in _MEDIAL_DEFINITION.finditer(unit):
        head = unit[: match.start()].strip(" ,;:-–—")
        body = unit[match.end() :].strip()
        if len(body) < 20 or not head:
            continue
        words = head.split()
        for size in range(min(4, len(words)), 0, -1):
            if _term_matches(" ".join(words[-size:]), target):
                return unit
    return ""


def _starts_with_term(sentence: str, target: str) -> bool:
    """True when the definition opens with the concept — the strongest shape."""
    return _term_matches(" ".join(sentence.split()[: min(4, len(target.split()) + 2)]), target)


# Verbs through which notes state what something *is* ("X is a Y", "X refers
# to ..."). Used to recognise definitional sentences — the one sentence a
# document spends defining its central terms is still real graph evidence,
# even when the pair never co-occurs again.
_DEFINITIONAL_VERBS = re.compile(
    r"\b(?:is|are|was|were|means?|refers?\s+to|is\s+defined\s+as|is\s+known\s+as|"
    r"include[sd]?|consists?\s+of|comprises?|involves?|deals?\s+with)\b",
    re.IGNORECASE,
)


def _same_concept_form(first: str, second: str) -> bool:
    """
    True when two labels are just two written forms of *one* concept, rather
    than two distinct concepts: an acronym and its expansion ("ML" and
    "Machine Learning", "AI" and "Artificial Intelligence").

    Only a one-word token whose letters spell the longer label's initials
    counts as an alias — "AI" is an alias of "Artificial Intelligence" but not
    of "computer science".
    """
    shorter, longer = (first, second) if len(first.split()) < len(second.split()) else (second, first)
    if len(shorter.split()) != 1:
        return normalize_for_match(first) == normalize_for_match(second)
    return _initials(longer) == shorter.strip().upper()


def _resolve_alias_mention(sentence: str, first: str, second: str) -> str:
    """
    Rewrite a bare-acronym mention in ``sentence`` to its expanded label, so
    definition matching sees the real pair.

    "So, we can define AI as ... a branch of computer science" checks the pair
    ("Artificial Intelligence", "computer science") against "Artificial
    Intelligence as ... a branch of computer science" instead of failing on the
    absent expansion text.

    The caller also passes the sentence's own acronym variants
    (``_ACRONYM.findall``); any single-word token whose letters spell a
    partner label's initials is expanded — "Machine Learning (ML): It is an
    application of AI ..." therefore tests ("Machine Learning",
    "Artificial Intelligence"), whether or not the full expansion is written.
    """
    resolved = sentence
    # Any bare token in the sentence whose letters spell a partner label's
    # initials is expanded — "Machine Learning (ML): It is an application of
    # AI ..." tests ("Machine Learning", "Artificial Intelligence") even though
    # the full expansion is never written. Tokens that mark their own label's
    # expansion ("(ML)" next to "Machine Learning") are expanded in place too,
    # collapsing the alias pair to one concept so `_same_concept_form` rejects
    # the degenerate pair ("ML", "Machine Learning") as one concept twice.
    bare_tokens = set(_ACRONYM.findall(sentence))
    for token in sorted(bare_tokens, key=len, reverse=True):
        for label in (first, second):
            if " " not in label.strip():
                continue
            if _initials(label) == token.strip().upper():
                pattern = re.compile(r"(?<![A-Za-z])" + re.escape(token) + r"(?![A-Za-z])")
                resolved = pattern.sub(label, resolved, count=1)
                break
    return resolved


def _is_definitional_sentence(sentence: str, first: str, second: str) -> bool:
    """
    True when the sentence states what one concept *is* in terms of the other.

    Both concept names must be present, they must be distinct, and a
    definitional verb must appear between them ("Artificial Intelligence is one
    of the booming technologies of computer science"). A sentence that merely
    mentions both ("The exam covers AI and ML") is not definitional.

    Acronyms and their expansions refer to the same thing, so they are not
    "definitional" pairs: "Natural Language Processing (NLP)" is one concept
    with two names, not two related concepts. Callers resolve acronyms to their
    canonical labels before calling, so the check here only needs to compare
    the resolved pair — and written text that still contains both raw forms
    ("ML" and "Machine Learning") is one and the same mention.
    """
    norm = (normalize_for_match(first), normalize_for_match(second))
    if norm[0] == norm[1]:
        return False
    if _same_concept_form(first, second):
        return False
    first_match = _word_bounded(first).search(sentence)
    second_match = _word_bounded(second).search(sentence)
    if not first_match or not second_match:
        return False
    start = min(first_match.start(), second_match.start())
    end = max(first_match.end(), second_match.end())
    return bool(_DEFINITIONAL_VERBS.search(sentence[start:end]))


def _trim_heading_prefix(sentence: str, label: str) -> str:
    """Drop a short slide/heading prefix ("The Advantage: ...") from a definition."""
    head, separator, tail = sentence.partition(":")
    if separator and len(head.split()) <= 5 and _word_bounded(label).search(tail):
        return tail.strip()
    return sentence


def find_definition(pages: Sequence[Tuple[int, str]], label: str) -> Tuple[str, str]:
    """
    Look for a definition sentence for ``label``.

    Returns ``(definition, snippet)`` — both empty when nothing is found, so the UI
    shows no definition rather than inventing one (brief §14).

    Every sentence that mentions the concept is examined, across every page: the
    previous implementation returned after the *first* mention, so a concept whose
    first appearance was a slide title ("Ascent: Hill Climbing") never got the
    definition that appears two pages later.
    """
    target = normalize_for_match(label)
    if not target:
        return "", ""

    pattern = _word_bounded(label)
    fallback = ""
    medial = ""

    for _page_number, text in pages:
        for sentence in _page_sentences(text):
            cleaned = _clean_sentence(sentence)
            if len(cleaned) < 25 or not pattern.search(cleaned):
                continue
            if not fallback:
                fallback = cleaned[:280]
            definition = _definition_sentence(cleaned, target)
            if not definition:
                continue
            trimmed = _trim_heading_prefix(definition, label)
            if _starts_with_term(trimmed, target):
                return trimmed[:300], definition[:280]
            medial = medial or trimmed

    if medial:
        return medial[:300], medial[:280]
    return "", fallback


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------
def extract_relations(
    pages: Sequence[Tuple[int, str]],
    concepts: Sequence[ConceptCandidate],
    *,
    max_relations_per_concept: int = 8,
    require_sentence_cooccurrence: bool = True,
) -> List[RelationCandidate]:
    """
    Derive typed edges from the text.

    Two sources of evidence:

    * **cue phrases** — a sentence mentioning two concepts and containing a cue
      phrase such as "requires" produces ``requires`` (``method = cue_phrase``),
    * **co-occurrence** — two concepts appearing in the *same sentence* at least
      twice in a document produce ``related_to`` (``method = cooccurrence``).
      A single *definitional* co-mention ("X is a Y" — a sentence stating what
      one concept is in terms of the other) also produces ``related_to``, with
      ``method = cooccurrence_definition``. Notes spend exactly one sentence
      defining their central terms, so without this the biggest concepts —
      "Artificial Intelligence", "Machine Learning" — stayed isolated.

    Explicit, typed edges always carry their page number and snippet so the UI
    can justify them. A single shared sentence no longer creates a weak edge:
    ``require_sentence_cooccurrence`` gates co-occurrence on repeated,
    sentence-level sightings.
    """
    pages = prepare_graph_pages(pages)

    labels = [concept.label for concept in concepts]
    if len(labels) < 2:
        return []

    relations: Dict[Tuple[str, str, str], RelationCandidate] = {}
    pair_counts: Counter = Counter()
    pair_page: Dict[Tuple[str, str], int] = {}
    per_concept: Counter = Counter()

    for page_number, text in pages:
        if not text:
            continue
        for sentence in _page_sentences(text):
            lowered = sentence.lower()
            present = [label for label in labels if label.lower() in lowered]
            # Acronym alias pass: a bare acronym ("AI") is a mention of its
            # expanded concept ("Artificial Intelligence"). Without this, sentences
            # that only use abbreviations — extremely common once a term has been
            # introduced — never connect the real concept to anything.
            for token in _ACRONYM.findall(sentence):
                for label in labels:
                    if label in present or label.lower() in lowered:
                        continue
                    if len(label.split()) >= 2 and _initials(label) == token:
                        present.append(label)
                        break
            if len(present) < 2:
                continue

            # --- cue-phrase relations ----------------------------------
            for pattern, relation_type, reversed_order in _CUE_PATTERNS:
                if not pattern.search(sentence):
                    continue
                # The alias pass adds bare acronyms ("AI") for concepts whose
                # expansion is not written out in this sentence. First drop bare
                # tokens that sit next to their own expansion ("(ML)" after
                # "Machine Learning") — one concept twice, not evidence — then
                # drop any remaining same-concept dupes, so a sentence never
                # produces a self-loop ("X is an application of X").
                for item in list(present):
                    if " " in item.strip():
                        continue
                    for other in present:
                        if other is item or " " not in other.strip():
                            continue
                        if _initials(other) == item.strip().upper():
                            present.remove(item)
                            break
                ordered = sorted(present, key=lambda entry: lowered.find(entry.lower()))
                deduped: List[str] = []
                for item in ordered:
                    if any(_same_concept_form(item, kept) for kept in deduped):
                        continue
                    deduped.append(item)
                ordered = deduped
                if len(ordered) < 2:
                    continue
                source, target = ordered[0], ordered[-1]
                if reversed_order:
                    source, target = target, source
                if source == target:
                    continue
                key = (slugify(source), slugify(target), relation_type)
                existing = relations.get(key)
                if existing:
                    existing.weight += 1.0
                    continue
                relations[key] = RelationCandidate(
                    source=source,
                    target=target,
                    relation=relation_type,
                    method="cue_phrase",
                    weight=1.0,
                    page_number=page_number,
                    snippet=sentence.strip()[:280],
                )

            # --- co-occurrence candidate pairs --------------------------
            # An exact duplicate mention ("Artificial Intelligence ...
            # Artificial Intelligence") must not count toward the repeated
            # co-occurrence gate — self-mentions are typography, not evidence.
            for index, first in enumerate(present):
                for second in present[index + 1 :]:
                    if first.lower() == second.lower():
                        continue
                    pair = tuple(sorted((first, second)))
                    pair_counts[pair] += 1
                    pair_page.setdefault(pair, page_number)

    # Co-occurrence edges, strongest first, capped per concept so the graph stays
    # readable instead of dense. A weak association requires *repeated*
    # sentence-level co-occurrence (single shared sentences are evidence-free
    # noise and must not become edges).
    #
    # Definitional sentences are authoritative even when seen once: a document
    # spends exactly one sentence saying "X is a Y" for its central terms
    # ("Artificial Intelligence is one of the booming technologies of computer
    # science"), so a single definitional co-mention is a real edge, while a
    # single *casual* co-mention is still rejected as noise. Acronyms are
    # folded into their expansions first ("AI" carries the mentions of
    # "Artificial Intelligence"), because central terms are introduced once by
    # name and then used by abbreviation ever after.
    pair_definitions: Dict[Tuple[str, str], Tuple[int, str]] = {}
    if require_sentence_cooccurrence:
        for page_number, text in pages:
            if not text:
                continue
            for sentence in _page_sentences(text):
                cleaned = _clean_sentence(sentence)
                if len(cleaned) < 25:
                    continue
                lowered = cleaned.lower()
                present = [label for label in labels if label.lower() in lowered]
                # Alias pass: a bare acronym ("AI") is a mention of its expanded
                # concept ("Artificial Intelligence"), which notes introduce once
                # by name and then use by abbreviation. Without this, definitional
                # sentences that use the acronym never connect the real concept.
                for token in _ACRONYM.findall(cleaned):
                    for label in labels:
                        if label in present:
                            continue
                        if label.lower() in lowered:
                            continue
                        if _initials(label) == token and label not in present:
                            present.append(label)
                            break
                if len(present) < 2:
                    continue
                # Bare tokens whose letters spell a *written-out* label's initials
                # sit next to their own expansion ("(ML)" after "Machine
                # Learning") — one concept twice, not evidence. Drop them so the
                # sentence can't pair a concept with itself.
                expanded_initials = {_initials(label) for label in present if " " in label.strip()}
                present = [
                    label
                    for label in present
                    if " " in label.strip() or label.strip().upper() not in expanded_initials
                ]
                if len(present) < 2:
                    continue
                # Bare tokens whose letters spell a *written-out* label's initials
                # sit next to their own expansion ("(ML)" after "Machine
                # Learning") — one concept twice, not evidence. Drop them so the
                # sentence can't pair a concept with itself.
                expanded_initials = {_initials(label) for label in present if " " in label.strip()}
                present = [
                    label
                    for label in present
                    if " " in label.strip() or label.strip().upper() not in expanded_initials
                ]
                if len(present) < 2:
                    continue
                for index, first in enumerate(present):
                    for second in present[index + 1 :]:
                        if first.lower() == second.lower():
                            continue
                        if _same_concept_form(first, second):
                            continue
                        pair = tuple(sorted((first, second)))
                        if pair not in pair_definitions and _is_definitional_sentence(
                            _resolve_alias_mention(cleaned, first, second), first, second
                        ):
                            pair_definitions[pair] = (page_number, cleaned.strip()[:280])
    for (first, second), count in pair_counts.most_common():
        pair = (first, second)
        definitional = pair_definitions.get(pair)
        if require_sentence_cooccurrence and count < 2 and definitional is None:
            continue
        if (
            per_concept[first] >= max_relations_per_concept
            or per_concept[second] >= max_relations_per_concept
        ):
            continue
        key = (slugify(first), slugify(second), "related_to")
        if key in relations:
            continue
        definitional_page: Optional[int] = None
        definitional_snippet = ""
        if definitional is not None:
            definitional_page, definitional_snippet = definitional
        relations[key] = RelationCandidate(
            source=first,
            target=second,
            relation="related_to",
            method="cooccurrence_definition" if definitional is not None else "cooccurrence",
            weight=min(3.0, 0.5 + count * 0.25) if definitional is None else 1.5,
            page_number=definitional_page if definitional is not None else pair_page.get((first, second)),
            snippet=definitional_snippet,
        )
        per_concept[first] += 1
        per_concept[second] += 1

    return sorted(relations.values(), key=lambda item: item.weight, reverse=True)


def candidate_labels(candidates: Sequence[ConceptCandidate]) -> List[str]:
    """Labels only — used when the LLM is asked to type relationships."""
    return [candidate.label for candidate in candidates]


def filter_relations_to_labels(
    relations: Iterable[RelationCandidate], labels: Sequence[str]
) -> List[RelationCandidate]:
    """Drop relations whose endpoints are not in the kept concept list."""
    allowed = {normalize_for_match(label) for label in labels}
    kept: List[RelationCandidate] = []
    for relation in relations:
        if (
            normalize_for_match(relation.source) in allowed
            and normalize_for_match(relation.target) in allowed
        ):
            kept.append(relation)
    return kept