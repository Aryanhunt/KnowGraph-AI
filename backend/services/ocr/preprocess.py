"""
OCR preprocessing pipeline (brief section 3 - preprocessing).

Improves OCR accuracy on scanned pages and photos by applying a configurable
chain of classical image-enhancement steps before the OCR engine sees the image.

Design rules:
  * The original page image is never modified -- a temporary processed copy is
    returned for OCR, and the original path is preserved for evidence/UI.
  * Every step is opt-in and configurable via backend/.env.
  * Only Pillow + numpy are used (already dependencies -- no OpenCV needed).
  * A maximum output dimension guards against memory explosions on large images.

Pipeline:

    original image (PIL.Image)
        down
    _validate (size guard)
        down
    optional preprocess (grayscale, upscale, denoise, contrast,
                         threshold, deskew, strip_borders, orientation)
        down
    processed image + metadata dict
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

MAX_OUTPUT_DIMENSION = 4000
MAX_PROCESSED_PIXELS = 12_000_000


@dataclass
class PreprocessConfig:
    """Which preprocessing steps are active and their parameters."""

    grayscale: bool = False
    upscale_factor: float = 1.0
    denoise: bool = False
    contrast_enhance: bool = False
    contrast_factor: float = 1.5
    thresholding: bool = False
    deskew: bool = False
    strip_borders: bool = False
    orientation: bool = True
    max_dimension: int = MAX_OUTPUT_DIMENSION


@dataclass
class PreprocessResult:
    """Output of preprocessing."""

    image_path: Path
    original_path: Path
    is_temp: bool
    preprocessing: Dict[str, Any] = field(default_factory=dict)
    width: int = 0
    height: int = 0
    warnings: list = field(default_factory=list)


def preprocess_image(image_path: Path, config: PreprocessConfig) -> PreprocessResult:
    """Load image_path, apply configured steps, return PreprocessResult.

    If no preprocessing is active the original path is returned unchanged
    (is_temp=False) so no unnecessary copy is created.
    """
    original = _load(image_path)
    if original is None:
        return PreprocessResult(
            image_path=Path(image_path),
            original_path=Path(image_path),
            is_temp=False,
            warnings=[f"Could not open image for preprocessing: {image_path}"],
        )

    metadata: Dict[str, Any] = {}
    image = original

    # Honour EXIF orientation.
    if config.orientation:
        before = image.size
        image = ImageOps.exif_transpose(image)
        if image.size != before:
            metadata["exif_orientation_applied"] = True

    # 1. Grayscale.
    if config.grayscale and image.mode != "L":
        image = image.convert("L")
        metadata["grayscale"] = True

    # 2. Upscale (helps Tesseract on small text).
    if config.upscale_factor > 1.0:
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        new_w = int(image.width * config.upscale_factor)
        new_h = int(image.height * config.upscale_factor)
        if new_w <= config.max_dimension and new_h <= config.max_dimension:
            image = image.resize((new_w, new_h), Image.LANCZOS)
            metadata["upscale_factor"] = config.upscale_factor

    # 3. Denoise (median filter removes salt-and-pepper).
    if config.denoise:
        image = image.filter(ImageFilter.MedianFilter(radius=1))
        metadata["denoise"] = True

        # 4. Contrast enhancement.
    if config.contrast_enhance:
        image = ImageEnhance.Contrast(image).enhance(config.contrast_factor)
        metadata["contrast_enhance"] = True
        metadata["contrast_factor"] = config.contrast_factor

    # 5. Adaptive thresholding / binarization (Otsu).
    if config.thresholding:
        image = _auto_threshold(image)
        metadata["thresholding"] = True

    # 6. Deskew.
    if config.deskew:
        gray_for_skew = image if image.mode == "L" else image.convert("L")
        color_source = image if image.mode != "L" else None
        image = _deskew(gray_for_skew, color_image=color_source)
        metadata["deskew"] = True

    # 7. Strip borders.
    if config.strip_borders:
        image = _strip_border(image)
        metadata["strip_borders"] = True

    # Safety: shrink if still too large.
    image = _enforce_size_limit(image, config.max_dimension)

    metadata["mode"] = image.mode
    metadata["width"] = image.width
    metadata["height"] = image.height

    # If any step actually changed the image, save a temp copy.
    changed = (
        config.grayscale and metadata.get("grayscale")
        or metadata.get("upscale_factor")
        or config.denoise
        or config.contrast_enhance
        or config.thresholding
        or config.deskew
        or config.strip_borders
        or metadata.get("exif_orientation_applied")
    )
    if changed:
        temp_path = _save_temp(image, image_path)
        return PreprocessResult(
            image_path=temp_path,
            original_path=Path(image_path),
            is_temp=True,
            preprocessing=_serializable(metadata),
            width=image.width,
            height=image.height,
            warnings=[],
        )

    return PreprocessResult(
        image_path=Path(image_path),
        original_path=Path(image_path),
        is_temp=False,
        preprocessing={},
        width=original.width,
        height=original.height,
        warnings=[],
    )


def build_config_from_settings(settings) -> PreprocessConfig:
    """Construct a PreprocessConfig from the application settings."""
    enabled = getattr(settings, "ocr_preprocess", True)
    steps_str = getattr(settings, "ocr_preprocess_steps", "")
    enabled_steps = {s.strip().lower() for s in steps_str.split(",") if s.strip()}

    def step(name: str, default: bool = False) -> bool:
        return enabled and (name in enabled_steps if enabled_steps else default)

    upscale = float(getattr(settings, "ocr_upscale_factor", 1.0) or 1.0)
    if upscale <= 0:
        upscale = 1.0

    return PreprocessConfig(
        grayscale=step("grayscale", default=True),
        upscale_factor=upscale,
        denoise=step("denoise"),
        contrast_enhance=step("contrast"),
        contrast_factor=float(getattr(settings, "ocr_contrast_factor", 1.5) or 1.5),
        thresholding=step("thresholding", default=True),
        deskew=step("deskew", default=True),
        strip_borders=step("strip_borders"),
        orientation=enabled,
        max_dimension=int(getattr(settings, "ocr_preprocess_max_dim", MAX_OUTPUT_DIMENSION)),
    )


def cleanup_temp(result: PreprocessResult) -> None:
    """Remove a temporary processed image if one was created."""
    if result.is_temp and result.image_path.exists():
        try:
            result.image_path.unlink()
        except OSError:
            pass
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load(image_path: Path) -> Optional[Image.Image]:
    try:
        image = Image.open(image_path)
        image.load()
        return image
    except Exception as exc:  # noqa: BLE001
        logger.warning("Preprocessing load failed for %s: %s", image_path, exc)
        return None


def _auto_threshold(image: Image.Image) -> Image.Image:
    """Binarize using Otsu's method (threshold on luminance)."""
    import numpy as np

    gray = image if image.mode == "L" else image.convert("L")
    arr = np.asarray(gray, dtype=np.uint8)
    if arr.size == 0:
        return gray
    hist, _ = np.histogram(arr, bins=256, range=(0, 256))
    total = arr.size
    sum_all = float(np.dot(hist, np.arange(256)))
    sum_b = 0.0
    w_b = 0.0
    max_between = 0.0
    threshold = 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += float(hist[t] * t)
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > max_between:
            max_between = between
            threshold = t
    return gray.point(lambda v: 0 if v < threshold else 255, mode="L")


def _deskew(gray_image: Image.Image, *, color_image) -> Image.Image:
    """Deskew using projection-profile variance."""
    binary = _auto_threshold(gray_image)
    arr = _to_numpy(binary)
    if arr.size < 100:
        return gray_image
    best_angle = 0.0
    best_score = -1.0
    for angle in range(-5, 6):
        rotated = _rotate_pil(binary, float(angle))
        score = _projection_variance(_to_numpy(rotated))
        if score > best_score:
            best_score = score
            best_angle = float(angle)
    if abs(best_angle) >= 0.5:
        if color_image is not None:
            return _rotate_pil(color_image, best_angle)
        return _rotate_pil(gray_image, best_angle)
    return gray_image


def _projection_variance(binary_arr) -> float:
    import numpy as np

    row_sums = np.sum(binary_arr, axis=1)
    if len(row_sums) < 2:
        return 0.0
    return float(np.var(row_sums))


def _rotate_pil(image: Image.Image, angle: float) -> Image.Image:
    fill = 255 if image.mode == "L" else (255, 255, 255)
    return image.rotate(angle * -1, expand=True, fillcolor=fill)


def _strip_border(image: Image.Image) -> Image.Image:
    """Crop a thin white margin around the image edge."""
    import numpy as np

    gray = image if image.mode == "L" else image.convert("L")
    arr = _to_numpy(gray)
    if arr.size == 0:
        return image
    non_white = arr < 250
    if not non_white.any():
        return image
    rows = np.any(non_white, axis=1)
    cols = np.any(non_white, axis=0)
    r_idx = rows.nonzero()[0]
    c_idx = cols.nonzero()[0]
    if len(r_idx) == 0 or len(c_idx) == 0:
        return image
    rmin, rmax = r_idx[[0, -1]]
    cmin, cmax = c_idx[[0, -1]]
    pad = 4
    return image.crop((max(0, cmin - pad), max(0, rmin - pad),
                        min(arr.shape[1], cmax + pad), min(arr.shape[0], rmax + pad)))


def _enforce_size_limit(image: Image.Image, max_dim: int) -> Image.Image:
    if image.width > max_dim or image.height > max_dim:
        ratio = min(max_dim / image.width, max_dim / image.height, 1.0)
        new_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
        return image.resize(new_size, Image.LANCZOS)
    return image


def _to_numpy(image: Image.Image):
    import numpy as np

    return np.asarray(image, dtype=np.uint8)


def _save_temp(image: Image.Image, original_path: Path) -> Path:
    suffix = original_path.suffix or ".png"
    stem = original_path.stem
    temp_path = original_path.with_name(f"{stem}__preprocessed{suffix}")
    fmt = image.format or "PNG"
    image.save(str(temp_path), format=fmt)
    return temp_path


def _serializable(metadata: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe
