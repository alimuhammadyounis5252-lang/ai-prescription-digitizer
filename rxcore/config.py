"""Configuration, read from environment variables (optionally from a .env file).

No secret is ever written in code. Copy .env.example to .env and fill it in.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _clean_env_value(value):
    """Strip quotes and an inline "# comment" from a .env value."""
    value = value.strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    cut = value.find(" #")
    if cut != -1:
        value = value[:cut]
    elif value.startswith("#"):
        value = ""
    return value.strip()


def load_dotenv(path=None):
    """Tiny .env reader (KEY=VALUE per line). Existing env vars win.

    Reads UTF-8 with or without a BOM (Windows Notepad adds one) and ignores
    an inline "# comment" after an unquoted value.
    """
    path = Path(path or ROOT / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), _clean_env_value(value))


@dataclass
class QualityThresholds:
    """Image quality limits.

    These are starting defaults, NOT calibrated values. Calibrate them on the
    project's own good/bad photos with tools/calibrate_quality.py before
    quoting them anywhere.
    """
    min_side_px: int = 300          # reject below this (text cannot be resolved)
    blank_std: float = 6.0          # reject below this (no ink on the page)
    warn_blur_var: float = 10.0     # warn below this (Laplacian variance at 1000px width)
    warn_dark_mean: float = 60.0    # warn below this mean brightness


@dataclass
class Settings:
    vlm_base_url: str = ""
    vlm_api_key: str = ""
    vlm_model: str = ""
    vlm_timeout_s: float = 120.0
    vlm_model_2: str = ""           # optional second reader (cross-check)
    vlm_base_url_2: str = ""        # defaults to vlm_base_url
    vlm_api_key_2: str = ""         # defaults to vlm_api_key
    access_code: str = ""           # optional: required to use the app when set
    host: str = "127.0.0.1"
    port: int = 5000
    max_upload_mb: int = 15
    max_image_side: int = 1600
    keep_uploads: bool = False
    data_dir: Path = ROOT / "data"
    records_dir: Path = ROOT / "records"
    uploads_dir: Path = ROOT / "uploads"
    formulary_path: Path = ROOT / "data" / "formulary.csv"
    quality: QualityThresholds = field(default_factory=QualityThresholds)

    @property
    def model_configured(self):
        return bool(self.vlm_base_url and self.vlm_model)


def get_settings():
    load_dotenv()
    env = os.environ.get
    return Settings(
        vlm_base_url=env("VLM_BASE_URL", "").rstrip("/"),
        vlm_api_key=env("VLM_API_KEY", ""),
        vlm_model=env("VLM_MODEL", ""),
        vlm_timeout_s=float(env("VLM_TIMEOUT_S", "120")),
        vlm_model_2=env("VLM_MODEL_2", ""),
        vlm_base_url_2=env("VLM_BASE_URL_2", "").rstrip("/"),
        vlm_api_key_2=env("VLM_API_KEY_2", ""),
        access_code=env("APP_ACCESS_CODE", ""),
        host=env("HOST", "127.0.0.1"),
        port=int(env("PORT", "5000")),
        max_upload_mb=int(env("MAX_UPLOAD_MB", "15")),
        keep_uploads=env("KEEP_UPLOADS", "0") == "1",
    )
