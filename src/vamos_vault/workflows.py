from __future__ import annotations

import asyncio
import csv
import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .config import load_config, resolve_data_path
from .db import Asset, VaultDB
from .media import build_caption, iter_media, normalize_tags, probe_media, sha256_file
from .telegram_client import download_file, list_remote_media, send_file
from .thumbnails import ensure_thumbnail_for_asset


ProgressCallback = Callable[[str, int, int], None]
StatusCallback = Callable[[str], None]


@dataclass
class PackageResult:
    folder: Path
    zip_path: Path | None
    metadata_csv: Path
    metadata_json: Path
    rows: list[dict]


def db_from_config(config: dict, base_dir: Path) -> VaultDB:
    return VaultDB(resolve_data_path(base_dir, config["vault"]["database"]))


def parse_caption(caption: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not caption:
        return parsed
    aliases = {
        "file": "filename",
        "project": "project",
        "shoot date": "shoot_date",
        "kind": "asset_kind",
        "scene": "scene",
        "location": "location",
        "people": "people",
        "rights": "rights",
        "rating": "rating",
        "youtube": "youtube_status",
        "tags": "tags",
        "notes": "notes",
    }
    for raw_line in caption.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        normalized_key = key.strip().lower()
        field = aliases.get(normalized_key)
        if field and value.strip():
            parsed[field] = value.strip()
    return parsed


def merge_tags(existing: str | None, extra: str | None) -> str | None:
    parts = []
    for value in [existing, extra]:
        normalized = normalize_tags(value)
        if normalized:
            parts.extend(normalized.split(","))
    return normalize_tags(",".join(parts))


def sync_remote_catalog(
    config: dict,
    base_dir: Path,
    *,
    limit: int = 100,
    project: str | None = None,
    tags: str | None = "phone,telegram",
    asset_kind: str = "original",
    thumbnails: bool = True,
) -> list[dict]:
    remote_items = asyncio.run(list_remote_media(config, base_dir, limit=limit, download_thumbnails=thumbnails))
    db = db_from_config(config, base_dir)
    rows: list[dict] = []
    normalized_tags = normalize_tags(tags)
    try:
        for item in remote_items:
            parsed = parse_caption(item.caption)
            key = f"tg:{config['telegram']['target']}:{item.message_id}"
            rating = parsed.get("rating")
            asset = Asset(
                path=f"telegram://{config['telegram']['target']}/{item.message_id}",
                filename=parsed.get("filename") or item.filename,
                size_bytes=item.size_bytes,
                sha256=key,
                asset_kind=parsed.get("asset_kind") or asset_kind,
                duration_seconds=item.duration_seconds,
                width=item.width,
                height=item.height,
                codec=item.mime_type,
                project=parsed.get("project") or project,
                shoot_date=parsed.get("shoot_date") or (item.date[:10] if item.date else None),
                tags=normalize_tags(parsed.get("tags")) or normalized_tags,
                scene=parsed.get("scene"),
                location=parsed.get("location"),
                people=parsed.get("people"),
                rights=parsed.get("rights"),
                rating=int(rating.split("/", 1)[0]) if rating and rating.split("/", 1)[0].isdigit() else None,
                youtube_status=parsed.get("youtube_status") or "raw",
                notes=parsed.get("notes") or item.caption,
                status="remote",
                telegram_chat=config["telegram"]["target"],
                telegram_message_id=item.message_id,
                telegram_link=item.link,
                uploaded_at=item.date,
                thumbnail_path=item.thumbnail_path,
                lossless=None if item.lossless is None else (1 if item.lossless else 0),
            )
            row = db.upsert_asset(asset)
            rows.append(dict(row))
    finally:
        db.close()
    return rows


def select_assets(
    db: VaultDB,
    *,
    query: str | None = None,
    sha_values: list[str] | None = None,
    projects: list[str] | None = None,
    statuses: list[str] | None = None,
    tags: list[str] | None = None,
    remote_only: bool = False,
    include_deleted: bool = False,
    limit: int | None = 500,
) -> list[dict]:
    rows = db.assets_for_filters(
        query=query,
        sha_values=sha_values,
        projects=projects,
        statuses=statuses,
        tags=tags,
        remote_only=remote_only,
        include_deleted=include_deleted,
        limit=limit,
    )
    return [dict(row) for row in rows]


def safe_name(value: object, fallback: str = "untitled") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:120] or fallback


def package_folder_for_asset(asset: dict, layout: str) -> Path:
    project = safe_name(asset.get("project"), "No Project")
    shoot_date = safe_name(asset.get("shoot_date"), "No Date")
    kind = safe_name(asset.get("asset_kind"), "original")
    status = safe_name(asset.get("status"), "status")
    if layout == "flat":
        return Path()
    if layout == "project":
        return Path(project)
    if layout == "project-date":
        return Path(project) / shoot_date
    if layout == "status-project":
        return Path(status) / project
    return Path(project) / shoot_date / kind


def unique_destination(folder: Path, filename: str) -> Path:
    destination = folder / safe_name(Path(filename).name, "media")
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    counter = 2
    while True:
        candidate = folder / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _write_package_metadata(package_dir: Path, rows: list[dict]) -> tuple[Path, Path]:
    csv_path = package_dir / "_vamos_metadata.csv"
    json_path = package_dir / "_vamos_metadata.json"
    json_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path, json_path


def _zip_folder(folder: Path, zip_path: Path) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for file_path in folder.rglob("*"):
            if file_path.is_file() and file_path != zip_path:
                archive.write(file_path, file_path.relative_to(folder))
    return zip_path


def create_remote_preview_thumbnail(
    config: dict,
    base_dir: Path,
    row: dict,
    *,
    progress_callback: ProgressCallback | None = None,
    status_callback: StatusCallback | None = None,
) -> str | None:
    message_id = row.get("telegram_message_id")
    if not message_id:
        return None
    if row.get("thumbnail_path") and Path(str(row["thumbnail_path"])).exists():
        return str(row["thumbnail_path"])

    cache_dir = resolve_data_path(base_dir, ".vamos-vault/preview-cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_name = f"{safe_name(row.get('sha256'), 'asset')}-{safe_name(row.get('filename'), 'media')}"
    downloaded_path: Path | None = None
    db = db_from_config(config, base_dir)
    try:
        if status_callback:
            status_callback(f"Fetching preview source: {row.get('filename')}")

        def on_progress(received: int, total: int) -> None:
            if progress_callback:
                progress_callback(str(row.get("filename") or ""), received, total)

        downloaded_path = asyncio.run(
            download_file(
                config,
                base_dir,
                message_id=int(message_id),
                out_dir=cache_dir,
                filename=cache_name,
                progress_callback=on_progress,
            )
        )
        thumbnail_path = ensure_thumbnail_for_asset(base_dir, row, source_path=downloaded_path)
        if thumbnail_path:
            db.set_thumbnail_path(str(row["sha256"]), thumbnail_path)
        return thumbnail_path
    finally:
        db.close()
        if downloaded_path is not None:
            try:
                downloaded_path.unlink(missing_ok=True)
            except OSError:
                pass


def create_download_package(
    config: dict,
    base_dir: Path,
    rows: Iterable[dict],
    *,
    out_dir: Path = Path("packs"),
    name: str | None = None,
    layout: str = "project-date-kind",
    make_zip: bool = True,
    reuse_downloaded: bool = True,
    progress_callback: ProgressCallback | None = None,
    status_callback: StatusCallback | None = None,
) -> PackageResult:
    assets = [dict(row) for row in rows]
    if not assets:
        raise ValueError("No assets selected for packaging.")

    base_label = name or assets[0].get("project") or "vamos-pack"
    package_name = safe_name(base_label, "vamos-pack")
    package_dir = out_dir / package_name
    package_dir.mkdir(parents=True, exist_ok=True)

    db = db_from_config(config, base_dir)
    packaged_rows: list[dict] = []
    try:
        for asset in assets:
            message_id = asset.get("telegram_message_id")
            if not message_id:
                continue
            relative_folder = package_folder_for_asset(asset, layout)
            destination_dir = package_dir / relative_folder
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = unique_destination(destination_dir, asset.get("filename") or "media")

            existing_path = Path(str(asset.get("downloaded_path") or ""))
            if reuse_downloaded and existing_path.exists() and existing_path.is_file():
                if status_callback:
                    status_callback(f"Copying existing local file: {asset.get('filename')}")
                if existing_path.resolve() != destination.resolve():
                    shutil.copy2(existing_path, destination)
            else:
                if status_callback:
                    status_callback(f"Downloading: {asset.get('filename')}")

                def on_progress(received: int, total: int) -> None:
                    if progress_callback:
                        progress_callback(str(asset.get("filename") or ""), received, total)

                downloaded = asyncio.run(
                    download_file(
                        config,
                        base_dir,
                        message_id=int(message_id),
                        out_dir=destination_dir,
                        filename=destination.name,
                        progress_callback=on_progress,
                    )
                )
                destination = Path(downloaded)

            content_hash = sha256_file(destination)
            updated = dict(
                db.mark_downloaded(
                    str(asset["sha256"]),
                    downloaded_path=str(destination.resolve()),
                    content_sha256=content_hash,
                )
            )
            thumbnail_path = ensure_thumbnail_for_asset(base_dir, updated, source_path=destination)
            if thumbnail_path:
                updated = dict(db.set_thumbnail_path(str(asset["sha256"]), thumbnail_path))
            updated["package_path"] = str(destination.resolve())
            packaged_rows.append(updated)

        if not packaged_rows:
            raise ValueError("Selected assets do not have Telegram media to download.")
        metadata_csv, metadata_json = _write_package_metadata(package_dir, packaged_rows)
        zip_path = _zip_folder(package_dir, package_dir.with_suffix(".zip")) if make_zip else None
    finally:
        db.close()

    return PackageResult(
        folder=package_dir,
        zip_path=zip_path,
        metadata_csv=metadata_csv,
        metadata_json=metadata_json,
        rows=packaged_rows,
    )


def upload_paths(
    config: dict,
    base_dir: Path,
    paths: list[Path],
    *,
    project: str | None = None,
    shoot_date: str | None = None,
    camera: str | None = None,
    lens: str | None = None,
    tags: str | None = None,
    asset_kind: str = "original",
    scene: str | None = None,
    location: str | None = None,
    people: str | None = None,
    rights: str | None = None,
    rating: int | None = None,
    favorite: bool = False,
    youtube_status: str | None = None,
    notes: str | None = None,
    dry_run: bool = False,
    recursive: bool = True,
    force: bool = False,
    progress_callback: ProgressCallback | None = None,
    status_callback: StatusCallback | None = None,
) -> list[dict]:
    """Catalog and upload originals to Telegram as documents.

    Mirrors the ``vamos-vault upload`` CLI command but reports progress through
    callbacks so the desktop app can drive it on a background thread. Returns one
    row dict per processed file (skipped duplicates included).
    """

    files = iter_media(paths, recursive=recursive)
    if not files:
        if status_callback:
            status_callback("No supported media files found.")
        return []

    max_size = int(config["vault"]["max_file_bytes"])
    caption_limit = int(config["vault"].get("caption_limit", 1024))
    normalized_tags = normalize_tags(tags)
    db = db_from_config(config, base_dir)
    rows: list[dict] = []
    try:
        for file_path in files:
            size = file_path.stat().st_size
            if size > max_size:
                if status_callback:
                    status_callback(f"Skipping oversized file: {file_path.name}")
                continue

            digest = sha256_file(file_path)
            existing = db.find_by_sha256(digest)
            if existing and existing["status"] == "uploaded" and not force:
                if status_callback:
                    status_callback(f"Already uploaded, skipping: {file_path.name}")
                rows.append(dict(existing))
                continue

            probe = probe_media(file_path)
            asset = Asset(
                path=str(file_path.resolve()),
                filename=file_path.name,
                size_bytes=size,
                sha256=digest,
                content_sha256=digest,
                asset_kind=asset_kind,
                duration_seconds=probe.duration_seconds,
                width=probe.width,
                height=probe.height,
                codec=probe.codec,
                project=project,
                shoot_date=shoot_date,
                camera=camera,
                lens=lens,
                tags=normalized_tags,
                scene=scene,
                location=location,
                people=people,
                rights=rights,
                rating=rating,
                favorite=1 if favorite else 0,
                youtube_status=youtube_status,
                notes=notes,
                status="dry-run" if dry_run else "cataloged",
                lossless=1,
            )
            row = dict(db.upsert_asset(asset))
            thumbnail_path = ensure_thumbnail_for_asset(base_dir, row, source_path=file_path)
            if thumbnail_path:
                row = dict(db.set_thumbnail_path(digest, thumbnail_path))
            if dry_run:
                rows.append(row)
                continue

            caption = build_caption(
                filename=file_path.name,
                size_bytes=size,
                sha256=digest,
                asset_kind=asset_kind,
                project=project,
                shoot_date=shoot_date,
                camera=camera,
                lens=lens,
                tags=normalized_tags,
                scene=scene,
                location=location,
                people=people,
                rights=rights,
                rating=rating,
                favorite=favorite,
                youtube_status=youtube_status,
                notes=notes,
                duration_seconds=probe.duration_seconds,
                limit=caption_limit,
            )
            if status_callback:
                status_callback(f"Uploading original: {file_path.name}")

            def on_progress(sent: int, total: int, _name: str = file_path.name) -> None:
                if progress_callback:
                    progress_callback(_name, sent, total)

            thumb = row.get("thumbnail_path")
            message_id, link = asyncio.run(
                send_file(
                    config,
                    base_dir,
                    file_path,
                    caption=caption,
                    thumb_path=Path(str(thumb)) if thumb else None,
                    progress_callback=on_progress,
                )
            )
            row = dict(
                db.mark_uploaded(
                    digest,
                    chat=config["telegram"]["target"],
                    message_id=message_id,
                    link=link,
                )
            )
            rows.append(row)
    finally:
        db.close()
    return rows


def current_config_and_db(base_dir: Path) -> tuple[dict, VaultDB]:
    config = load_config(base_dir)
    return config, db_from_config(config, base_dir)
