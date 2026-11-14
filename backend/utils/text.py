"""
Text cleaning, sentence splitting and lightweight linguistic helpers.

These are *traditional* algorithms (regex + word statistics), not LLM calls.
Brief §26.13 asks for reliable classical methods wherever an LLM is not needed,
and the concept/keyword scoring used by the knowledge graph is built on top of
this module.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Iterable, List

# A compact English stopword list — enough for keyword scoring and the language
# heuristic without pulling an NLP dependency into the project.
STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are aren't as at be because been
    before being below between both but by can cannot could couldn't did didn't do does doesn't
    doing don't down during each few for from further had hadn't has hasn't have haven't having
    he her here hers herself him himself his how however i if in into is isn't it its itself
    just let's me more most mustn't my myself no nor not of off on once only or other ought our
    ours ourselves out over own same shan't she should shouldn't so some such than that the their
    theirs them themselves then there these they this those through to too under until up very
    was wasn't we were weren't what when where which while who whom why will with won't would
    wouldn't you your yours yourself yourselves thus hence therefore may might shall
    """.split()
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACES = re.compile(r"[ \t\u00a0]{2,}")
_MULTI_NEWLINES = re.compile(r"\n{3,}")
_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n{2,}")
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']{1,}")
_NON_WORD_EDGE = re.compile(r"^[^\w(]+|[^\w)]+$")
_PAGE_NOISE = re.compile(r"^\s*(page\s*)?\d{1,4}\s*$", re.IGNORECASE)


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs and cap consecutive newlines at two."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub(" ", text)
    text = _MULTI_SPACES.sub(" ", text)
    return _MULTI_NEWLINES.sub("\n\n", text)


def clean_text(text: str, *, drop_page_noise: bool = True) -> str:
    """
    Clean extracted/OCR text before chunking.

    Handles the artefacts that both PDF extraction and OCR produce: soft hyphen
    line breaks (``infor-\\nmation``), stray control characters, ragged spacing
    and lines that contain nothing but a page number.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)
    # Replace common OCR/PDF bullet and quote artefacts with plain ASCII.
    text = (text.replace("\uf0b7", "- ").replace("\u2022", "- ")
                .replace("\u2018", "'").replace("\u2019", "'")
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u2013", "-").replace("\u2014", "-"))
    text = normalize_whitespace(text)

    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if drop_page_noise and _PAGE_NOISE.match(stripped):
            continue
        lines.append(re.sub(r"[ \t]{2,}", " ", stripped))
    return _MULTI_NEWLINES.sub("\n\n", "\n".join(lines)).strip()


def usable_char_count(text: str) -> int:
    """Count characters that carry meaning (letters/digits), ignoring layout."""
    return sum(1 for char in text or "" if char.isalnum())


def is_meaningful_text(text: str, min_chars: int = 20) -> bool:
    """True when the text is worth storing (used by the OCR fallback decision)."""
    return usable_char_count(text) >= max(1, min_chars)


def detect_language(text: str) -> str:
    """
    Very small heuristic language tag.

    Measures how much of the text is made of English function words and returns
    ``en`` when that share is high enough, otherwise ``unknown``. It never
    claims a language it cannot verify; the UI presents ``unknown`` as
    "not detected" rather than as an error.
    """
    words = _WORD.findall((text or "").lower())
    if len(words) < 20:
        return "unknown"
    stopword_hits = sum(1 for word in words if word in STOPWORDS)
    return "en" if stopword_hits / len(words) >= 0.08 else "unknown"


def split_sentences(text: str) -> List[str]:
    """Split prose into sentences (OCR blocks and tables stay as single items)."""
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def tokenize(text: str) -> List[str]:
    """Lowercased word tokens without stopwords (used for keyword scoring)."""
    return [word for word in _WORD.findall((text or "").lower()) if word not in STOPWORDS]


def raw_words(text: str) -> List[str]:
    """
    Lowercased word tokens *including* stopwords, in reading order.

    Keyword scoring wants stopwords gone, but phrase detection must keep them:
    dropping them first makes the words either side look adjacent, which is how a
    table of "Job A Job B / Job E Job F" labels produced the "concept" *job job*.
    """
    return [match.group(0).lower() for match in _WORD.finditer(text or "")]


_SENTENCE_END = re.compile(r"[.!?:;]\s*$")
_JOINABLE_END = re.compile(r"[,;:\-–—]\s*$")


def reflow_lines(text: str) -> str:
    """
    Join hard-wrapped lines back into readable sentences.

    PDF and slide exports wrap prose mid-sentence
    (``"... Hill Climbing is incredibly\\nmemory efficient."``), which hides the
    definitions and cue phrases that actually straddle the break. A line is joined
    to the next one when the next starts with a lowercase letter and the current
    line does not already end a sentence — the same rule a human applies when
    re-reading a wrapped paragraph. Headings and list items are left alone.
    """
    if not text:
        return ""
    lines: List[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if lines and lines[-1]:
            previous = lines[-1]
            wrapped = not _SENTENCE_END.search(previous) and (
                line[:1].islower() or bool(_JOINABLE_END.search(previous))
            )
            if wrapped:
                lines[-1] = f"{previous} {line}"
                continue
        lines.append(line)
    return "\n".join(lines)


def keyword_scores(text: str, *, top_n: int = 40) -> List[tuple]:
    """Frequency-based keyword ranking: ``[(word, count), ...]``."""
    return Counter(tokenize(text)).most_common(top_n)


def extractive_summary(text: str, *, max_sentences: int = 4, max_chars: int = 900) -> str:
    """
    Build a summary *without* an LLM.

    Sentences are scored by keyword density and the best ones are kept in their
    original order. Used as the fallback whenever Ollama is unavailable and as
    the deterministic baseline the LLM summary can be compared against.
    """
    sentences = [s for s in split_sentences(text) if usable_char_count(s) > 40]
    if not sentences:
        return truncate(clean_text(text), max_chars)
    frequencies = Counter(tokenize(text))
    if not frequencies:
        return truncate(" ".join(sentences[:max_sentences]), max_chars)

    def score(sentence: str) -> float:
        words = tokenize(sentence)
        if not words:
            return 0.0
        return sum(frequencies.get(word, 0) for word in words) / (len(words) ** 0.5)

    ranked = sorted(range(len(sentences)), key=lambda i: score(sentences[i]), reverse=True)
    chosen = sorted(ranked[:max_sentences])
    return truncate(" ".join(sentences[i] for i in chosen), max_chars)


def truncate(text: str, max_chars: int, *, suffix: str = "...") -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - len(suffix))].rstrip() + suffix


def normalize_for_match(text: str) -> str:
    """Lowercase and strip punctuation so keyword filters can be compared."""
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def slugify(text: str, *, max_length: int = 80) -> str:
    """Stable id fragment (``Functional Dependency`` → ``functional-dependency``)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_length] or "concept"


def clean_concept_label(label: str) -> str:
    """Normalise a candidate concept string extracted from prose.

    Leading articles are stripped ("A candidate key" becomes "candidate key"): a
    definition sentence like "A candidate key is ..." captures "A candidate key"
    as the term, and cards/questions read better without the article.
    """
    label = _NON_WORD_EDGE.sub("", (label or "").strip())
    label = normalize_whitespace(label).replace("  ", " ")
    label = label.strip(" -,:;.")
    lowered = label.lower()
    for article in ("a ", "an ", "the "):
        if lowered.startswith(article) and len(label) > len(article) + 2:
            return label[len(article):].strip()
    return label


def first_heading(text: str, max_length: int = 200) -> str:
    """Best-effort title: the first non-trivial line of a document."""
    for line in (text or "").split("\n"):
        candidate = line.strip(" #\t")
        if usable_char_count(candidate) >= 4 and len(candidate) <= max_length:
            return candidate
    return ""


def dedupe_preserving_order(items: Iterable[str]) -> List[str]:
    """Case/punctuation-insensitive de-duplication that keeps the first form."""
    seen = set()
    result: List[str] = []
    for item in items:
        key = normalize_for_match(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result