"""Image loading and quality checks (Pillow + NumPy only).

The quality gate has two outcomes:
  * reject  - the image cannot be read at all (too small, or a blank page).
              Recognition is NOT run, so nothing can be invented.
  * warn    - recognition runs, and the warning is shown to the pharmacist.
"""
import io

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import QualityThresholds


class InvalidImage(ValueError):
    pass


def load_image(data):
    """Decode bytes into an upright RGB image, or raise InvalidImage."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError as exc:      # not an OSError, so it needs its own clause
        raise InvalidImage("Image is too large to process") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise InvalidImage("File is not a readable image") from exc
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:                                # damaged EXIF block: keep the pixels as they are
        pass
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        # Transparent pixels would turn black on convert("RGB") and hide the writing.
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, rgba)
    return img.convert("RGB")


def _laplacian_variance(gray):
    """Variance of the 4-neighbour Laplacian: low value = few sharp edges."""
    g = gray.astype(np.float32)
    if g.shape[0] < 3 or g.shape[1] < 3:             # too small for a 3x3 stencil; avoids NaN
        return 0.0
    lap = (-4.0 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1]
           + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def assess_quality(img, thresholds=None):
    t = thresholds or QualityThresholds()
    w, h = img.size
    # Measure at a fixed width so numbers are comparable between photos.
    scale = 1000.0 / max(w, 1)
    small = img.convert("L").resize((1000, max(1, int(h * scale))))
    gray = np.asarray(small)

    metrics = {
        "width": w,
        "height": h,
        "brightness_mean": round(float(gray.mean()), 1),
        "contrast_std": round(float(gray.std()), 1),
        "blur_laplacian_var": round(_laplacian_variance(gray), 1),
        "glare_fraction": round(float((gray >= 250).mean()), 3),
    }

    reject, warnings = [], []
    if min(w, h) < t.min_side_px:
        reject.append("Image is too small to read. Take a closer, larger photo.")
    if metrics["contrast_std"] < t.blank_std:
        reject.append("No handwriting detected (the page looks blank).")
    if not reject:
        if metrics["blur_laplacian_var"] < t.warn_blur_var:
            warnings.append("Photo may be blurred.")
        if metrics["brightness_mean"] < t.warn_dark_mean:
            warnings.append("Photo is dark.")
        # glare_fraction is reported but not used for a warning yet: white paper
        # is bright everywhere, so a fixed limit gives false alarms. Calibrate first.

    return {
        "ok": not reject,
        "reject_reasons": reject,
        "warnings": warnings,
        "metrics": metrics,
        "thresholds_calibrated": False,
    }


def to_jpeg_bytes(img, max_side=1600, quality=90):
    """Downscale (never upscale) and encode for sending to the model."""
    w, h = img.size
    scale = min(1.0, float(max_side) / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
