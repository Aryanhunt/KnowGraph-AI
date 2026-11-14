"""
OCR quality assessment (brief section 3 -- quality).

Tesseract (and any OCR engine) reports a per-word confidence number, but that
number alone is *not* enough to decide whether a page is usable: a page of
random noise can score 99 and still be garbage, while a clean photo of typed
notes in a familiar font can score 55.

This module computes a deterministic, configurable quality report from:

  * the engine's confidence (average and, when available, the minimum),
  * the recognised text (word count, char count, suspicious characters,
    repeated-character patterns, character-to-word ratio),
  * whether the page was actually OCR processed (vs. digital text),
  * whether the OCR pass succeeded at all.

The labels ``good`` / ``acceptable`` / ``needs_review`` / ``poor`` /
``unreadable`` are based on documented, configurable rules -- never on a
fabricated "AI confidence" score (brief section 15).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.text import usable_char_count

logger = logging.getLogger(__name__)

#: Ordered from worst to best.
QUALITY_LABELS = ("unreadable", "poor", "needs_review", "acceptable", "good")

#: Default thresholds -- all configurable via .env.
DEFAULT_QUALITY_THRESHOLDS = {
    "good_min_confidence": 80.0,
    "acceptable_min_confidence": 60.0,
    "min_words": 5,
    "max_suspicious_char_ratio": 0.15,
    "max_repeated_char_ratio": 0.20,
    "min_char_per_word": 3.0,
    "max_char_per_word": 12.0,
}

# Characters unusual in normal English text but common in OCR errors.
_SUSPICIOUS_CHARS = re.compile(r"[^A-Za-z0-9\s.,!?;:'\"()\-/\n]")


@dataclass
class QualityMetrics:
    """Raw numbers computed from the OCR result."""

    average_confidence: Optional[float] = None
    min_confidence: Optional[float] = None
    word_count: int = 0
    char_count: int = 0
    suspicious_char_ratio: float = 0.0
    repeated_char_ratio: float = 0.0
    char_per_word: float = 0.0
    ocr_used: bool = False
    ocr_ok: bool = True


@dataclass
class QualityReport:
    """The complete quality assessment for one page."""

    label: str
    metrics: QualityMetrics
    warnings: List[str] = field(default_factory=list)
    engine: str = ""
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "engine": self.engine,
            "metrics": {
                "average_confidence": self.metrics.average_confidence,
                "min_confidence": self.metrics.min_confidence,
                "word_count": self.metrics.word_count,
                "char_count": self.metrics.char_count,
                "suspicious_char_ratio": round(self.metrics.suspicious_char_ratio, 4),
                "repeated_char_ratio": round(self.metrics.repeated_char_ratio, 4),
                "char_per_word": round(self.metrics.char_per_word, 2),
                "ocr_used": self.metrics.ocr_used,
                "ocr_ok": self.metrics.ocr_ok,
            },
            "warnings": list(self.warnings),
        }


def assess_quality(
    text: str,
    confidence: Optional[float],
    *,
    ocr_used: bool = True,
    ocr_ok: bool = True,
    engine: str = "",
    word_confidences: Optional[List[float]] = None,
    thresholds: Optional[Dict[str, Any]] = None,
) -> QualityReport:
    """Assess the quality of an OCR result."""
    thresholds = {**DEFAULT_QUALITY_THRESHOLDS, **(thresholds or {})}

    text = text or ""
    metrics = _compute_metrics(
        text, confidence, ocr_used, ocr_ok, word_confidences
    )

    warnings: List[str] = []
    label = _classify(metrics, thresholds, warnings)

    if not ocr_used:
        label = "good" if metrics.char_count > 0 else "unreadable"
        if metrics.char_count == 0:
            warnings.append(
                "This page was not processed by OCR and contains no text."
            )

    if ocr_used and not ocr_ok:
        label = "unreadable"
        if metrics.char_count == 0:
            warnings.append(
                "OCR could not extract any text from this page."
            )

    return QualityReport(
        label=label,
        metrics=metrics,
        warnings=warnings,
        engine=engine,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _compute_metrics(
    text: str,
    confidence: Optional[float],
    ocr_used: bool,
    ocr_ok: bool,
    word_confidences: Optional[List[float]],
) -> QualityMetrics:
    words = text.split()
    word_count = len(words)
    char_count = usable_char_count(text)

    suspicious_count = 0
    total_non_space = 0
    for char in text:
        if char.isspace():
            continue
        total_non_space += 1
        if _SUSPICIOUS_CHARS.match(char):
            suspicious_count += 1
    suspicious_ratio = (
        suspicious_count / total_non_space if total_non_space else 0.0
    )

    # Repeated character detection: runs like "llll" or "oooo".
    repeated_count = 0
    for word in words:
        lower = word.lower()
        for char in set(lower):
            if char.isalpha():
                max_run = 1
                current = 1
                for i in range(1, len(lower)):
                    if lower[i] == lower[i - 1]:
                        current += 1
                        max_run = max(max_run, current)
                    else:
                        current = 1
                if max_run >= 4:
                    repeated_count += max_run
    repeated_ratio = (repeated_count / max(char_count, 1)) if char_count else 0.0

    char_per_word = (char_count / word_count) if word_count else 0.0

    min_conf = None
    if word_confidences:
        valid = [c for c in word_confidences if c is not None and c >= 0]
        if valid:
            min_conf = round(min(valid), 1)

    return QualityMetrics(
        average_confidence=confidence,
        min_confidence=min_conf,
        word_count=word_count,
        char_count=char_count,
        suspicious_char_ratio=round(suspicious_ratio, 4),
        repeated_char_ratio=round(repeated_ratio, 4),
        char_per_word=round(char_per_word, 2),
        ocr_used=ocr_used,
        ocr_ok=ocr_ok,
    )


def _classify(
    metrics: QualityMetrics, thresholds: Dict[str, Any], warnings: List[str]
) -> str:
    """Assign a quality label based on metrics and thresholds."""
    good_min = thresholds["good_min_confidence"]
    acceptable_min = thresholds["acceptable_min_confidence"]
    min_words = thresholds["min_words"]
    max_suspicious = thresholds["max_suspicious_char_ratio"]
    max_repeated = thresholds["max_repeated_char_ratio"]
    min_cpw = thresholds["min_char_per_word"]
    max_cpw = thresholds["max_char_per_word"]

    if metrics.char_count == 0 or not metrics.ocr_ok:
        warnings.append(
            "OCR output is empty -- this page may be blank or unreadable."
        )
        return "unreadable"

    if metrics.word_count < min_words:
        warnings.append(
            f"Very few words recognised ({metrics.word_count} < {min_words})."
        )

    confidence = metrics.average_confidence

    if confidence is not None:
        if confidence < acceptable_min:
            warnings.append(
                f"Low OCR confidence: {confidence:.1f}% "
                f"(below {acceptable_min:.0f}%)."
            )
        if confidence < good_min:
            warnings.append(
                f"Confidence {confidence:.1f}% is below the good-quality "
                f"threshold of {good_min:.0f}%."
            )
    else:
        warnings.append(
            "The OCR engine did not report a confidence value."
        )

    if metrics.suspicious_char_ratio > max_suspicious:
        warnings.append(
            f"Unusual characters make up {metrics.suspicious_char_ratio:.1%} "
            f"of the text (above {max_suspicious:.0%})."
        )

    if metrics.repeated_char_ratio > max_repeated:
        warnings.append(
            f"Excessive repeated characters detected "
            f"(ratio {metrics.repeated_char_ratio:.2f})."
        )

    if metrics.char_per_word < min_cpw or metrics.char_per_word > max_cpw:
        warnings.append(
            f"Unusual character-to-word ratio ({metrics.char_per_word:.1f})."
        )

    # Classify.
    too_few_words = metrics.word_count < min_words
    if confidence is not None:
        if confidence >= good_min:
            if (
                too_few_words
                or metrics.suspicious_char_ratio > max_suspicious
                or metrics.repeated_char_ratio > max_repeated
                or metrics.char_per_word < min_cpw
                or metrics.char_per_word > max_cpw
            ):
                return "needs_review"
            return "good"
        if confidence >= acceptable_min:
            if (
                too_few_words
                or metrics.suspicious_char_ratio > max_suspicious
                or metrics.repeated_char_ratio > max_repeated
            ):
                return "needs_review"
            return "acceptable"

    # Confidence is None or below acceptable_min.
    if confidence is not None and confidence < acceptable_min:
        return "poor"
    if metrics.word_count < min_words:
        return "poor"
    return "needs_review"
