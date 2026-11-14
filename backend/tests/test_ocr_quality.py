"""
OCR quality pipeline tests: preprocessing, quality labels and page flags.

Hermetic: preprocessing uses synthetic PIL images, quality assessment is a pure
function. Tesseract is exercised only where the engine is available.
"""

import pytest

from services.ocr.preprocess import (
    PreprocessConfig,
    build_config_from_settings,
    cleanup_temp,
    preprocess_image,
)
from services.ocr.quality import (
    DEFAULT_QUALITY_THRESHOLDS,
    QUALITY_LABELS,
    assess_quality,
)


# ---------------------------------------------------------------------------
# Phase 2 - preprocessing
# ---------------------------------------------------------------------------
def _write_image(tmp_path, size=(400, 200), color="white"):
    from PIL import Image

    path = tmp_path / "test.png"
    Image.new("RGB", size, color).save(str(path), format="PNG")
    return path


def test_preprocess_disabled_returns_original(tmp_path):
    path = _write_image(tmp_path)
    result = preprocess_image(path, PreprocessConfig())
    assert result.is_temp is False
    assert result.image_path == path
    assert result.preprocessing == {}


def test_preprocess_grayscale_and_upscale(tmp_path):
    path = _write_image(tmp_path)
    config = PreprocessConfig(grayscale=True, upscale_factor=2.0)
    result = preprocess_image(path, config)
    try:
        assert result.is_temp is True
        assert result.preprocessing.get("grayscale") is True
        assert result.preprocessing.get("upscale_factor") == 2.0
        assert result.width == 800 and result.height == 400
        assert result.image_path.exists()
        from PIL import Image

        with Image.open(path) as handle:
            assert handle.size == (400, 200)
    finally:
        cleanup_temp(result)
        assert not result.image_path.exists()


def test_preprocess_creates_binarized_image(tmp_path):
    path = _write_image(tmp_path)
    config = PreprocessConfig(grayscale=True, thresholding=True)
    result = preprocess_image(path, config)
    try:
        assert result.is_temp is True
        assert result.preprocessing.get("thresholding") is True
        from PIL import Image
        import numpy as np

        arr = np.asarray(Image.open(result.image_path).convert("L"))
        unique = set(int(v) for v in arr.flat)
        assert unique.issubset({0, 255}), f"expected pure binary, got {unique}"
    finally:
        cleanup_temp(result)


def test_preprocess_config_from_settings():
    class FakeSettings:
        ocr_preprocess = True
        ocr_preprocess_steps = "grayscale,thresholding"
        ocr_upscale_factor = 2.0
        ocr_contrast_factor = 1.5
        ocr_preprocess_max_dim = 3000

    config = build_config_from_settings(FakeSettings())
    assert config.grayscale is True
    assert config.thresholding is True
    assert config.deskew is False, "steps list must disable unlisted defaults"
    assert config.upscale_factor == 2.0

    class Disabled:
        ocr_preprocess = False
        ocr_preprocess_steps = ""
        ocr_upscale_factor = 1.0
        ocr_contrast_factor = 1.5
        ocr_preprocess_max_dim = 4000

    off = build_config_from_settings(Disabled())
    assert off.grayscale is False and off.thresholding is False


def test_preprocess_handles_unreadable_file(tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    result = preprocess_image(bad, PreprocessConfig(grayscale=True))
    assert result.is_temp is False
    assert result.warnings


# ---------------------------------------------------------------------------
# Phase 3 - quality assessment
# ---------------------------------------------------------------------------
GOOD_TEXT = (
    "A functional dependency X -> Y means that Y is functionally dependent on X. "
    "BCNF requires every determinant to be a superkey. Normalization reduces "
    "redundancy and improves data integrity across relations."
)


def test_quality_labels_are_ordered():
    assert QUALITY_LABELS == ("unreadable", "poor", "needs_review", "acceptable", "good")


def test_good_text_with_high_confidence_is_good():
    report = assess_quality(GOOD_TEXT, 92.0, ocr_used=True, ocr_ok=True, engine="tesseract")
    assert report.label == "good"
    assert report.metrics.word_count > 5
    assert report.metrics.char_per_word > 0


def test_low_confidence_is_poor():
    report = assess_quality(GOOD_TEXT, 40.0, ocr_used=True, ocr_ok=True)
    assert report.label == "poor"
    assert any("confidence" in warning.lower() for warning in report.warnings)


def test_moderate_confidence_is_acceptable():
    report = assess_quality(GOOD_TEXT, 70.0, ocr_used=True, ocr_ok=True)
    assert report.label == "acceptable"


def test_failed_ocr_is_unreadable():
    report = assess_quality("", None, ocr_used=True, ocr_ok=False, engine="tesseract")
    assert report.label == "unreadable"
    assert report.metrics.ocr_ok is False


def test_empty_output_is_unreadable():
    report = assess_quality("   ", 95.0, ocr_used=True, ocr_ok=True)
    assert report.label == "unreadable"


def test_digital_page_without_ocr_is_good():
    report = assess_quality(GOOD_TEXT, None, ocr_used=False, ocr_ok=True)
    assert report.label == "good"


def test_few_words_is_flagged():
    report = assess_quality("just three words", 90.0, ocr_used=True, ocr_ok=True)
    assert report.label in {"poor", "needs_review"}
    assert report.metrics.word_count == 3


def test_suspicious_chars_cause_review():
    weird = "The answer is ▓▒░ @@@ ### !!! ~~~ for chapter one two three."
    report = assess_quality(weird, 90.0, ocr_used=True, ocr_ok=True)
    assert report.label in {"needs_review", "poor"}


def test_repeated_characters_cause_review():
    repeated = "The value is gggg gggg gggg for the given sample input data."
    report = assess_quality(repeated, 90.0, ocr_used=True, ocr_ok=True)
    assert report.label in {"needs_review", "poor"}


def test_thresholds_are_configurable():
    strict = {**DEFAULT_QUALITY_THRESHOLDS, "good_min_confidence": 95.0}
    report = assess_quality(GOOD_TEXT, 92.0, thresholds=strict)
    assert report.label != "good"


def test_min_confidence_from_word_confidences():
    report = assess_quality(
        GOOD_TEXT, 90.0, word_confidences=[90.0, 85.0, 55.0, 92.0]
    )
    assert report.metrics.min_confidence == 55.0


def test_report_to_dict_shape():
    report = assess_quality(GOOD_TEXT, 88.0, engine="tesseract")
    payload = report.to_dict()
    assert payload["label"] == "good"
    assert payload["engine"] == "tesseract"
    assert "word_count" in payload["metrics"]
    assert isinstance(payload["warnings"], list)
