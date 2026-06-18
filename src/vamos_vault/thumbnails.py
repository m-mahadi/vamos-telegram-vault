from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from .config import resolve_data_path

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional UI enhancement
    Image = None


VIDEO_SUFFIXES = {
    ".3g2",
    ".3gp",
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".mxf",
    ".webm",
}
IMAGE_SUFFIXES = {".avif", ".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def is_video_asset(row: Mapping[str, object]) -> bool:
    codec = str(row.get("codec") or "").lower()
    filename = str(row.get("filename") or row.get("downloaded_path") or row.get("path") or "").lower()
    return codec.startswith("video/") or Path(filename).suffix.lower() in VIDEO_SUFFIXES


def is_image_asset(row: Mapping[str, object]) -> bool:
    codec = str(row.get("codec") or "").lower()
    filename = str(row.get("filename") or row.get("downloaded_path") or row.get("path") or "").lower()
    return codec.startswith("image/") or Path(filename).suffix.lower() in IMAGE_SUFFIXES


def _ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return str(exe)
    except Exception:
        pass
    return shutil.which("ffmpeg")


def thumbnail_backend_label() -> str:
    return "ffmpeg ready" if _ffmpeg_exe() else "ffmpeg missing"


def _safe_key(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        text = "asset"
    return "".join(ch if ch.isalnum() else "-" for ch in text).strip("-")[:80] or "asset"


def _thumbnail_dir(base_dir: Path) -> Path:
    path = resolve_data_path(base_dir, ".vamos-vault/thumbs/generated")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _thumbnail_path(base_dir: Path, row: Mapping[str, object], source_path: Path | None) -> Path:
    key = row.get("sha256")
    if not key and source_path is not None:
        key = hashlib.sha1(str(source_path.resolve()).encode("utf-8")).hexdigest()
    return _thumbnail_dir(base_dir) / f"{_safe_key(key)}.jpg"


def _valid_existing(path: object) -> str | None:
    if not path:
        return None
    candidate = Path(str(path))
    if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
        return str(candidate)
    return None


def _source_from_row(row: Mapping[str, object], source_path: Path | None) -> Path | None:
    if source_path is not None:
        return source_path
    for key in ("downloaded_path", "path"):
        value = row.get(key)
        if not value:
            continue
        text = str(value)
        if text.startswith("telegram://"):
            continue
        candidate = Path(text)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _save_image_thumbnail(source: Path, destination: Path) -> str | None:
    if Image is None:
        return None
    try:
        with Image.open(source) as image:
            image.thumbnail((720, 720))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(destination, "JPEG", quality=88, optimize=True)
    except Exception:
        if destination.exists():
            destination.unlink(missing_ok=True)
        return None
    return str(destination) if destination.exists() and destination.stat().st_size > 0 else None


def _video_thumbnail(source: Path, destination: Path) -> str | None:
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    for timestamp in ("00:00:01", "00:00:00.2", "00:00:00"):
        if destination.exists():
            destination.unlink(missing_ok=True)
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            timestamp,
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=720:-2",
            "-q:v",
            "3",
            str(destination),
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=45, creationflags=flags)
        except Exception:
            continue
        if destination.exists() and destination.stat().st_size > 0:
            return str(destination)
    return None


def ensure_thumbnail_for_asset(
    base_dir: Path,
    row: Mapping[str, object],
    *,
    source_path: Path | None = None,
) -> str | None:
    """Return an existing or generated thumbnail path for a local asset.

    Telegram-only assets can only use Telegram-provided thumbnails because the
    original video bytes are not local yet. Once the original is downloaded,
    this creates a poster frame without changing the original file.
    """

    existing = _valid_existing(row.get("thumbnail_path"))
    if existing:
        return existing
    source = _source_from_row(row, source_path)
    if source is None:
        return None
    destination = _thumbnail_path(base_dir, row, source)
    existing = _valid_existing(destination)
    if existing:
        return existing
    if is_image_asset(row):
        return _save_image_thumbnail(source, destination)
    if is_video_asset(row):
        return _video_thumbnail(source, destination)
    return None
