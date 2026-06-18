from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TransferSpeedColumn
from rich.table import Table

from .config import (
    CONFIG_FILE,
    FREE_FILE_LIMIT_BYTES,
    PREMIUM_FILE_LIMIT_BYTES,
    load_config,
    resolve_data_path,
    telegram_credentials,
    write_config,
)
from .db import Asset, VaultDB
from .media import (
    build_caption,
    format_bytes,
    format_duration,
    iter_media,
    normalize_tags,
    probe_media,
    sha256_file,
)
from .reports import build_manifest, enrich_assets_for_display, write_manifest, write_studio_html
from .telegram_client import TelegramConfigError, authenticate, download_file, send_file
from .telegram_client import delete_message
from .thumbnails import ensure_thumbnail_for_asset, thumbnail_backend_label
from .workflows import create_download_package, merge_tags, select_assets, sync_remote_catalog


app = typer.Typer(help="Telegram-backed video archive for vlog and cinematography workflows.")
queue_app = typer.Typer(help="Manage the persistent download list.")
app.add_typer(queue_app, name="queue")
console = Console()


def _db_from_config(config: dict, base_dir: Path) -> VaultDB:
    return VaultDB(resolve_data_path(base_dir, config["vault"]["database"]))


def _render_rows(rows: list[dict]) -> None:
    table = Table(show_lines=False)
    table.add_column("File", overflow="fold")
    table.add_column("Project")
    table.add_column("Kind")
    table.add_column("Size", justify="right")
    table.add_column("Dur", justify="right")
    table.add_column("Tags")
    table.add_column("Rating", justify="right")
    table.add_column("Status")
    table.add_column("Telegram")
    for row in rows:
        table.add_row(
            row.get("filename") or "",
            row.get("project") or "",
            row.get("asset_kind") or "",
            format_bytes(int(row.get("size_bytes") or 0)),
            format_duration(row.get("duration_seconds")),
            row.get("tags") or "",
            f"{row.get('rating')}/5" if row.get("rating") else "",
            row.get("status") or "",
            row.get("telegram_link") or "",
        )
    console.print(table)


def _current_manifest(config: dict, db: VaultDB) -> dict:
    assets = enrich_assets_for_display([dict(row) for row in db.all_assets()])
    return build_manifest(config=config, stats=db.stats(), assets=assets)


def _parse_caption(caption: str | None) -> dict[str, str]:
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


def _safe_unlink(path: str | None) -> bool:
    if not path:
        return False
    target = Path(path)
    if not target.exists() or not target.is_file():
        return False
    target.unlink()
    return True


def _option_list(values: list[str] | None) -> list[str] | None:
    cleaned = [value.strip() for value in values or [] if value and value.strip()]
    return cleaned or None


def _tag_option_list(values: list[str] | None) -> list[str] | None:
    cleaned: list[str] = []
    for value in values or []:
        normalized = normalize_tags(value)
        if normalized:
            cleaned.extend(normalized.split(","))
    return cleaned or None


def _select_rows_from_cli(
    db: VaultDB,
    *,
    query: str | None = None,
    sha: list[str] | None = None,
    project: list[str] | None = None,
    status: list[str] | None = None,
    tag: list[str] | None = None,
    remote_only: bool = False,
    include_deleted: bool = False,
    limit: int | None = 500,
) -> list[dict]:
    return select_assets(
        db,
        query=query,
        sha_values=_option_list(sha),
        projects=_option_list(project),
        statuses=_option_list(status),
        tags=_tag_option_list(tag),
        remote_only=remote_only,
        include_deleted=include_deleted,
        limit=limit,
    )


def _render_package_result(result: object) -> None:
    console.print(f"Package folder: {result.folder}")  # type: ignore[attr-defined]
    if result.zip_path:  # type: ignore[attr-defined]
        console.print(f"ZIP file: {result.zip_path}")  # type: ignore[attr-defined]
    console.print(f"Metadata CSV: {result.metadata_csv}")  # type: ignore[attr-defined]
    console.print(f"Metadata JSON: {result.metadata_json}")  # type: ignore[attr-defined]
    _render_rows(result.rows)  # type: ignore[attr-defined]


@app.command()
def init(
    target: Annotated[str, typer.Option(help="Telegram destination: me, @channel, invite link, or ID.")] = "me",
    premium: Annotated[bool, typer.Option(help="Allow 4 GB max file size instead of 2 GB.")] = False,
    database: Annotated[str | None, typer.Option(help="SQLite database path.")] = None,
) -> None:
    """Create vault.json and the local data directory."""
    path = write_config(Path.cwd(), target=target, premium=premium, database=database)
    limit = PREMIUM_FILE_LIMIT_BYTES if premium else FREE_FILE_LIMIT_BYTES
    console.print(f"Created {path}")
    console.print(f"Target: {target}")
    console.print(f"Max file size: {format_bytes(limit)}")


@app.command()
def auth() -> None:
    """Log in to Telegram and create a local session."""
    config = load_config(Path.cwd())
    try:
        asyncio.run(authenticate(config, Path.cwd()))
    except TelegramConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc
    console.print("Telegram session is ready.")


@app.command()
def doctor() -> None:
    """Check local setup."""
    import shutil

    base_dir = Path.cwd()
    config = load_config(base_dir)
    api_id, api_hash = telegram_credentials()
    table = Table(title="Vamos Vault Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_row(CONFIG_FILE, "ok" if (base_dir / CONFIG_FILE).exists() else "missing")
    table.add_row("TELEGRAM_API_ID", "ok" if api_id else "missing")
    table.add_row("TELEGRAM_API_HASH", "ok" if api_hash else "missing")
    table.add_row("Target", config["telegram"]["target"])
    table.add_row("Upload mode", "original-quality Telegram documents")
    table.add_row("Database", str(resolve_data_path(base_dir, config["vault"]["database"])))
    table.add_row("Max file size", format_bytes(int(config["vault"]["max_file_bytes"])))
    table.add_row("ffprobe", shutil.which("ffprobe") or "missing - duration/resolution metadata disabled")
    table.add_row("Video thumbnails", thumbnail_backend_label())
    console.print(table)


@app.command(name="app")
def desktop_app() -> None:
    """Open the native Vamos Vault desktop app."""
    from .desktop import main

    main()


@app.command()
def upload(
    paths: Annotated[list[Path], typer.Argument(help="Files or folders to upload/catalog.")],
    project: Annotated[str | None, typer.Option(help="Project or vlog name.")] = None,
    shoot_date: Annotated[str | None, typer.Option(help="Shoot date, ideally YYYY-MM-DD.")] = None,
    camera: Annotated[str | None, typer.Option(help="Camera body or recording device.")] = None,
    lens: Annotated[str | None, typer.Option(help="Lens or focal range.")] = None,
    tags: Annotated[str | None, typer.Option(help="Comma-separated tags.")] = None,
    asset_kind: Annotated[str, typer.Option(help="original, proxy, thumbnail, audio, project-file, etc.")] = "original",
    scene: Annotated[str | None, typer.Option(help="Scene, sequence, or roll label.")] = None,
    location: Annotated[str | None, typer.Option(help="Shoot location.")] = None,
    people: Annotated[str | None, typer.Option(help="People visible or credited in the asset.")] = None,
    rights: Annotated[str | None, typer.Option(help="Usage rights, release, or license note.")] = None,
    rating: Annotated[int | None, typer.Option(help="Creator rating from 1 to 5.")] = None,
    favorite: Annotated[bool, typer.Option(help="Mark as a favorite/select.")] = False,
    youtube_status: Annotated[str | None, typer.Option(help="raw, selected, editing, published, short, unused, etc.")] = None,
    notes: Annotated[str | None, typer.Option(help="Short production notes.")] = None,
    dry_run: Annotated[bool, typer.Option(help="Catalog/check without uploading.")] = False,
    recursive: Annotated[bool, typer.Option(help="Scan folders recursively.")] = True,
    force: Annotated[bool, typer.Option(help="Upload even if SHA-256 already exists.")] = False,
) -> None:
    """Catalog media files and upload originals as Telegram documents."""
    if rating is not None and not 1 <= rating <= 5:
        console.print("Rating must be between 1 and 5.")
        raise typer.Exit(1)

    base_dir = Path.cwd()
    config = load_config(base_dir)
    db = _db_from_config(config, base_dir)
    files = iter_media(paths, recursive=recursive)
    if not files:
        console.print("No supported media files found.")
        raise typer.Exit(1)

    max_size = int(config["vault"]["max_file_bytes"])
    normalized_tags = normalize_tags(tags)
    rows_for_output: list[dict] = []

    try:
        for file_path in files:
            size = file_path.stat().st_size
            if size > max_size:
                console.print(
                    f"Skipping oversized file: {file_path} "
                    f"({format_bytes(size)} > {format_bytes(max_size)})"
                )
                continue

            digest = sha256_file(file_path)
            existing = db.find_by_sha256(digest)
            if existing and existing["status"] == "uploaded" and not force:
                console.print(f"Already uploaded, skipping: {file_path.name}")
                rows_for_output.append(dict(existing))
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
            )
            row = db.upsert_asset(asset)
            thumbnail_path = ensure_thumbnail_for_asset(base_dir, dict(row), source_path=file_path)
            if thumbnail_path:
                row = db.set_thumbnail_path(digest, thumbnail_path)
            rows_for_output.append(dict(row))
            if dry_run:
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
                limit=int(config["vault"]["caption_limit"]),
            )

            console.print(f"Uploading original-quality document: {file_path.name}")
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TransferSpeedColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task(file_path.name, total=size)

                def update_progress(sent: int, total: int) -> None:
                    progress.update(task_id, completed=sent, total=total)

                message_id, link = asyncio.run(
                    send_file(
                        config,
                        base_dir,
                        file_path,
                        caption=caption,
                        thumb_path=Path(str(row["thumbnail_path"])) if row["thumbnail_path"] else None,
                        progress_callback=update_progress,
                    )
                )
            uploaded = db.mark_uploaded(
                digest,
                chat=config["telegram"]["target"],
                message_id=message_id,
                link=link,
            )
            rows_for_output[-1] = dict(uploaded)
    finally:
        db.close()

    _render_rows(rows_for_output)


@app.command()
def sync(
    limit: Annotated[int, typer.Option(help="Number of latest Telegram messages to scan.")] = 100,
    project: Annotated[str | None, typer.Option(help="Fallback project for phone uploads without captions.")] = None,
    tags: Annotated[str | None, typer.Option(help="Fallback comma-separated tags.")] = "phone,telegram",
    asset_kind: Annotated[str, typer.Option(help="Fallback asset kind.")] = "original",
    thumbnails: Annotated[bool, typer.Option(help="Download lightweight Telegram thumbnails when available.")] = True,
) -> None:
    """Catalog media already sent to the Telegram vault from phone or desktop."""
    base_dir = Path.cwd()
    config = load_config(base_dir)
    try:
        rows = sync_remote_catalog(
            config,
            base_dir,
            limit=limit,
            project=project,
            tags=tags,
            asset_kind=asset_kind,
            thumbnails=thumbnails,
        )
    except TelegramConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc

    console.print(f"Synced {len(rows)} remote media files from Telegram.")
    _render_rows(rows[:25])


@app.command()
def download(
    query: Annotated[str, typer.Argument(help="SHA-256, filename, project, tag, scene, or location.")],
    out: Annotated[Path, typer.Option(help="Folder to write downloaded originals.")] = Path("downloads"),
    limit: Annotated[int, typer.Option(help="Maximum matching uploaded assets to download.")] = 1,
) -> None:
    """Download original files back from Telegram using the local catalog."""
    base_dir = Path.cwd()
    config = load_config(base_dir)
    db = _db_from_config(config, base_dir)
    try:
        rows = [dict(row) for row in db.remote_assets_for_query(query, limit=limit)]

        if not rows:
            console.print("No remote catalog entries matched that query. Run `vamos-vault sync` first if the video was sent from your phone.")
            raise typer.Exit(1)

        downloaded_rows: list[dict] = []
        for row in rows:
            size = int(row.get("size_bytes") or 0)
            console.print(f"Downloading: {row['filename']}")
            try:
                with Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    TransferSpeedColumn(),
                    console=console,
                ) as progress:
                    task_id = progress.add_task(row["filename"], total=size)

                    def update_progress(received: int, total: int) -> None:
                        progress.update(task_id, completed=received, total=total)

                    path = asyncio.run(
                        download_file(
                            config,
                            base_dir,
                            message_id=int(row["telegram_message_id"]),
                            out_dir=out,
                            filename=row["filename"],
                            progress_callback=update_progress,
                        )
                    )
            except TelegramConfigError as exc:
                console.print(str(exc))
                raise typer.Exit(1) from exc
            content_hash = sha256_file(path)
            downloaded = db.mark_downloaded(
                row["sha256"],
                downloaded_path=str(path.resolve()),
                content_sha256=content_hash,
            )
            thumbnail_path = ensure_thumbnail_for_asset(base_dir, dict(downloaded), source_path=path)
            if thumbnail_path:
                downloaded = db.set_thumbnail_path(row["sha256"], thumbnail_path)
            downloaded_rows.append(dict(downloaded))
            console.print(f"Saved {path}")
    finally:
        db.close()

    _render_rows(downloaded_rows)


@app.command()
def metadata(
    query: Annotated[str | None, typer.Argument(help="Optional search query to update.")] = None,
    sha: Annotated[list[str] | None, typer.Option("--sha", help="Exact asset SHA/catalog ID. Repeatable.")] = None,
    project_filter: Annotated[list[str] | None, typer.Option("--project-filter", help="Only update this existing project. Repeatable.")] = None,
    status_filter: Annotated[list[str] | None, typer.Option("--status-filter", help="Only update this status. Repeatable.")] = None,
    tag_filter: Annotated[list[str] | None, typer.Option("--tag-filter", help="Only update rows containing this tag. Repeatable.")] = None,
    project: Annotated[str | None, typer.Option(help="Set project / virtual folder.")] = None,
    shoot_date: Annotated[str | None, typer.Option(help="Set shoot date, ideally YYYY-MM-DD.")] = None,
    camera: Annotated[str | None, typer.Option(help="Set camera or phone model.")] = None,
    lens: Annotated[str | None, typer.Option(help="Set lens or focal range.")] = None,
    tags: Annotated[str | None, typer.Option(help="Replace tags with this comma-separated list.")] = None,
    append_tags: Annotated[str | None, typer.Option(help="Append tags without removing existing tags.")] = None,
    asset_kind: Annotated[str | None, typer.Option(help="Set kind: original, broll, talking-head, audio, project-file, etc.")] = None,
    scene: Annotated[str | None, typer.Option(help="Set scene or sequence.")] = None,
    location: Annotated[str | None, typer.Option(help="Set shoot location.")] = None,
    people: Annotated[str | None, typer.Option(help="Set visible people or credits.")] = None,
    rights: Annotated[str | None, typer.Option(help="Set rights/release/licensing note.")] = None,
    rating: Annotated[int | None, typer.Option(help="Set 1-5 rating.")] = None,
    favorite: Annotated[bool | None, typer.Option("--favorite/--no-favorite", help="Mark or unmark favorite.")] = None,
    youtube_status: Annotated[str | None, typer.Option(help="Set YouTube/editorial status: raw, selected, editing, published, unused.")] = None,
    notes: Annotated[str | None, typer.Option(help="Replace notes.")] = None,
    clear: Annotated[list[str] | None, typer.Option("--clear", help="Clear a metadata field. Repeatable.")] = None,
    limit: Annotated[int, typer.Option(help="Maximum matching rows to update.")] = 100,
    yes: Annotated[bool, typer.Option("--yes", help="Required when updating multiple rows.")] = False,
) -> None:
    """Bulk edit local production metadata without renaming anything in Telegram."""
    if rating is not None and not 1 <= rating <= 5:
        console.print("Rating must be between 1 and 5.")
        raise typer.Exit(1)

    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        rows = _select_rows_from_cli(
            db,
            query=query,
            sha=sha,
            project=project_filter,
            status=status_filter,
            tag=tag_filter,
            limit=limit,
            include_deleted=True,
        )
        if not rows:
            console.print("No catalog entries matched.")
            raise typer.Exit(1)
        if len(rows) > 1 and not yes:
            console.print(f"Refusing to update {len(rows)} rows without --yes.")
            raise typer.Exit(1)

        updates: dict[str, object | None] = {}
        simple_updates = {
            "project": project,
            "shoot_date": shoot_date,
            "camera": camera,
            "lens": lens,
            "asset_kind": asset_kind,
            "scene": scene,
            "location": location,
            "people": people,
            "rights": rights,
            "rating": rating,
            "youtube_status": youtube_status,
            "notes": notes,
        }
        for field, value in simple_updates.items():
            if value is not None:
                updates[field] = value
        if tags is not None:
            updates["tags"] = normalize_tags(tags)
        if favorite is not None:
            updates["favorite"] = 1 if favorite else 0
        for field in clear or []:
            updates[field] = None

        if not updates and append_tags is None:
            console.print("No metadata changes requested.")
            raise typer.Exit(1)

        changed: list[dict] = []
        if append_tags is not None:
            for row in rows:
                per_row = dict(updates)
                per_row["tags"] = merge_tags(row.get("tags"), append_tags)
                changed.extend(dict(item) for item in db.update_metadata([row["sha256"]], per_row))
        else:
            changed = [dict(item) for item in db.update_metadata([row["sha256"] for row in rows], updates)]
    finally:
        db.close()

    console.print(f"Updated metadata for {len(changed)} assets.")
    _render_rows(changed)


@app.command()
def pack(
    query: Annotated[str | None, typer.Argument(help="Optional search query to package.")] = None,
    project: Annotated[list[str] | None, typer.Option("--project", help="Project / virtual folder to package. Repeatable.")] = None,
    sha: Annotated[list[str] | None, typer.Option("--sha", help="Exact asset SHA/catalog ID. Repeatable.")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Tag to package. Repeatable.")] = None,
    status: Annotated[list[str] | None, typer.Option("--status", help="Status to include. Repeatable.")] = None,
    out: Annotated[Path, typer.Option(help="Folder where package folders and zips are written.")] = Path("packs"),
    name: Annotated[str | None, typer.Option(help="Package folder/zip name.")] = None,
    layout: Annotated[str, typer.Option(help="flat, project, project-date, project-date-kind, or status-project.")] = "project-date-kind",
    zip_output: Annotated[bool, typer.Option("--zip/--no-zip", help="Create a ZIP next to the package folder.")] = True,
    limit: Annotated[int, typer.Option(help="Maximum selected assets.")] = 500,
) -> None:
    """Download selected Telegram originals into working folders and optional ZIP."""
    if layout not in {"flat", "project", "project-date", "project-date-kind", "status-project"}:
        console.print("Layout must be one of: flat, project, project-date, project-date-kind, status-project.")
        raise typer.Exit(1)
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        rows = _select_rows_from_cli(
            db,
            query=query,
            sha=sha,
            project=project,
            status=status,
            tag=tag,
            remote_only=True,
            limit=limit,
        )
    finally:
        db.close()
    if not rows:
        console.print("No downloadable Telegram assets matched.")
        raise typer.Exit(1)

    def status_line(message: str) -> None:
        console.print(message)

    try:
        result = create_download_package(
            config,
            Path.cwd(),
            rows,
            out_dir=out,
            name=name,
            layout=layout,
            make_zip=zip_output,
            status_callback=status_line,
        )
    except (TelegramConfigError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc
    _render_package_result(result)


@queue_app.command(name="add")
def queue_add(
    query: Annotated[str | None, typer.Argument(help="Optional search query to queue.")] = None,
    project: Annotated[list[str] | None, typer.Option("--project", help="Project / virtual folder to queue. Repeatable.")] = None,
    sha: Annotated[list[str] | None, typer.Option("--sha", help="Exact asset SHA/catalog ID. Repeatable.")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Tag to queue. Repeatable.")] = None,
    status: Annotated[list[str] | None, typer.Option("--status", help="Status to queue. Repeatable.")] = None,
    note: Annotated[str | None, typer.Option(help="Optional queue note.")] = None,
    limit: Annotated[int, typer.Option(help="Maximum selected assets.")] = 100,
) -> None:
    """Add matching assets to the persistent download list."""
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        rows = _select_rows_from_cli(
            db,
            query=query,
            sha=sha,
            project=project,
            status=status,
            tag=tag,
            remote_only=True,
            limit=limit,
        )
        if not rows:
            console.print("No downloadable Telegram assets matched.")
            raise typer.Exit(1)
        queued = db.add_to_queue([row["sha256"] for row in rows], note=note)
    finally:
        db.close()
    console.print(f"Queued {len(rows)} assets. Download list now has {len(queued)} assets.")
    _render_rows([dict(row) for row in queued])


@queue_app.command(name="list")
def queue_list() -> None:
    """Show the persistent download list."""
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        rows = [dict(row) for row in db.queued_assets()]
    finally:
        db.close()
    _render_rows(rows)


@queue_app.command(name="remove")
def queue_remove(
    query: Annotated[str, typer.Argument(help="Search query or exact SHA to remove from the download list.")],
    limit: Annotated[int, typer.Option(help="Maximum matched rows to remove.")] = 20,
) -> None:
    """Remove matching items from the download list."""
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        rows = _select_rows_from_cli(db, query=query, include_deleted=True, limit=limit)
        if not rows:
            exact = db.find_by_sha256(query)
            rows = [dict(exact)] if exact else []
        removed = db.remove_from_queue([row["sha256"] for row in rows])
    finally:
        db.close()
    console.print(f"Removed {removed} queued assets.")


@queue_app.command(name="clear")
def queue_clear(yes: Annotated[bool, typer.Option("--yes", help="Confirm clearing the download list.")] = False) -> None:
    """Clear the download list."""
    if not yes:
        console.print("Refusing to clear the download list without --yes.")
        raise typer.Exit(1)
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        removed = db.clear_queue()
    finally:
        db.close()
    console.print(f"Cleared {removed} queued assets.")


@queue_app.command(name="pack")
def queue_pack(
    out: Annotated[Path, typer.Option(help="Folder where package folders and zips are written.")] = Path("packs"),
    name: Annotated[str | None, typer.Option(help="Package folder/zip name.")] = "download-list",
    layout: Annotated[str, typer.Option(help="flat, project, project-date, project-date-kind, or status-project.")] = "project-date-kind",
    zip_output: Annotated[bool, typer.Option("--zip/--no-zip", help="Create a ZIP next to the package folder.")] = True,
    clear_after: Annotated[bool, typer.Option(help="Clear queue after a successful package.")] = False,
) -> None:
    """Download the persistent download list into folders and optional ZIP."""
    if layout not in {"flat", "project", "project-date", "project-date-kind", "status-project"}:
        console.print("Layout must be one of: flat, project, project-date, project-date-kind, status-project.")
        raise typer.Exit(1)
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        rows = [dict(row) for row in db.queued_assets()]
    finally:
        db.close()
    if not rows:
        console.print("Download list is empty.")
        raise typer.Exit(1)

    def status_line(message: str) -> None:
        console.print(message)

    try:
        result = create_download_package(
            config,
            Path.cwd(),
            rows,
            out_dir=out,
            name=name,
            layout=layout,
            make_zip=zip_output,
            status_callback=status_line,
        )
    except (TelegramConfigError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc

    if clear_after:
        db = _db_from_config(config, Path.cwd())
        try:
            db.clear_queue()
        finally:
            db.close()
    _render_package_result(result)


@app.command()
def done(
    query: Annotated[str, typer.Argument(help="SHA, filename, project, tag, scene, or location to mark done.")],
    notes: Annotated[str | None, typer.Option(help="Completion note.")] = None,
    delete_local: Annotated[bool, typer.Option(help="Delete the downloaded local PC copy.")] = False,
    delete_remote: Annotated[bool, typer.Option(help="Delete the Telegram vault message too.")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Required when deleting local or remote files.")] = False,
) -> None:
    """Mark work complete and optionally delete local/remote copies."""
    if (delete_local or delete_remote) and not yes:
        console.print("Refusing to delete anything without --yes.")
        raise typer.Exit(1)

    base_dir = Path.cwd()
    config = load_config(base_dir)
    db = _db_from_config(config, base_dir)
    try:
        row = db.first_asset_for_query(query)
        if row is None:
            console.print("No catalog entry matched that query.")
            raise typer.Exit(1)

        changed = db.mark_done(row["sha256"], notes=notes)
        if delete_local:
            deleted = _safe_unlink(changed["downloaded_path"])
            console.print("Deleted local copy." if deleted else "No local downloaded copy found to delete.")
        if delete_remote:
            if changed["telegram_message_id"] is None:
                console.print("No Telegram message ID found for remote deletion.")
            else:
                try:
                    asyncio.run(delete_message(config, base_dir, message_id=int(changed["telegram_message_id"])))
                except TelegramConfigError as exc:
                    console.print(str(exc))
                    raise typer.Exit(1) from exc
                changed = db.mark_remote_deleted(row["sha256"])
                console.print("Deleted Telegram vault message.")
    finally:
        db.close()

    _render_rows([dict(changed)])


@app.command(name="list")
def list_assets(
    limit: Annotated[int, typer.Option(help="Number of rows to show.")] = 50,
) -> None:
    """Show recent vault entries."""
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        rows = [dict(row) for row in db.list_assets(limit=limit)]
    finally:
        db.close()
    _render_rows(rows)


@app.command()
def find(
    query: Annotated[str, typer.Argument(help="Search filename, project, tags, notes, camera, or lens.")],
    limit: Annotated[int, typer.Option(help="Number of rows to show.")] = 50,
) -> None:
    """Search the local production catalog."""
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        rows = [dict(row) for row in db.search(query, limit=limit)]
    finally:
        db.close()
    _render_rows(rows)


@app.command()
def export(
    fmt: Annotated[str, typer.Option("--format", help="csv or json.")] = "csv",
    out: Annotated[Path | None, typer.Option(help="Output file path.")] = None,
) -> None:
    """Export the local catalog."""
    if fmt not in {"csv", "json"}:
        console.print("Format must be csv or json.")
        raise typer.Exit(1)

    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    destination = out or Path("exports") / f"vamos-catalog.{fmt}"
    try:
        path = db.export(destination, fmt)  # type: ignore[arg-type]
    finally:
        db.close()
    console.print(f"Exported {path}")


@app.command()
def manifest(
    out: Annotated[Path, typer.Option(help="Manifest output path.")] = Path("exports/vamos-manifest.json"),
) -> None:
    """Export a future-app-friendly JSON manifest."""
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        data = _current_manifest(config, db)
        path = write_manifest(out, data)
    finally:
        db.close()
    console.print(f"Exported {path}")


@app.command()
def studio(
    out: Annotated[Path, typer.Option(help="HTML dashboard output path.")] = Path(".vamos-vault/studio/index.html"),
    open_browser: Annotated[bool, typer.Option("--open", help="Open the generated Studio in your browser.")] = False,
) -> None:
    """Generate an offline Studio dashboard for browsing the vault."""
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        data = _current_manifest(config, db)
        path = write_studio_html(out, data)
    finally:
        db.close()
    console.print(f"Generated {path}")
    if open_browser:
        webbrowser.open(path.resolve().as_uri())


@app.command()
def summary() -> None:
    """Show vault totals and per-project archive size."""
    config = load_config(Path.cwd())
    db = _db_from_config(config, Path.cwd())
    try:
        stats = db.stats()
    finally:
        db.close()

    console.print(f"Assets: {stats['total_assets']}")
    console.print(f"Remote-only: {stats['remote_assets']}")
    console.print(f"Downloaded: {stats['downloaded_assets']}")
    console.print(f"Done: {stats['done_assets']}")
    console.print(f"Remote-deleted: {stats['remote_deleted_assets']}")
    console.print(f"Uploaded: {stats['uploaded_assets']}")
    console.print(f"Favorites: {stats['favorites']}")
    console.print(f"Needs metadata: {stats['needs_metadata']}")
    console.print(f"Storage: {format_bytes(int(stats['total_bytes']))}")
    console.print(f"Runtime: {format_duration(float(stats['total_duration_seconds']))}")

    table = Table(title="Projects")
    table.add_column("Project")
    table.add_column("Assets", justify="right")
    table.add_column("States")
    table.add_column("Fav", justify="right")
    table.add_column("Storage", justify="right")
    table.add_column("Runtime", justify="right")
    table.add_column("Updated")
    for project in stats["projects"]:
        states = " ".join(
            part
            for part in [
                f"R:{project['remote_assets']}" if int(project["remote_assets"]) else "",
                f"DL:{project['downloaded_assets']}" if int(project["downloaded_assets"]) else "",
                f"Done:{project['done_assets']}" if int(project["done_assets"]) else "",
                f"Del:{project['remote_deleted_assets']}" if int(project["remote_deleted_assets"]) else "",
            ]
            if part
        ) or "-"
        table.add_row(
            str(project["project"]),
            str(project["assets"]),
            states,
            str(project["favorites"]),
            format_bytes(int(project["bytes"] or 0)),
            format_duration(float(project["duration_seconds"] or 0)),
            str(project["updated_at"] or "")[:10],
        )
    console.print(table)


if __name__ == "__main__":
    app()
