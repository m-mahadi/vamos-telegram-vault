from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Asset:
    path: str
    filename: str
    size_bytes: int
    sha256: str
    content_sha256: str | None = None
    asset_kind: str = "original"
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    project: str | None = None
    shoot_date: str | None = None
    camera: str | None = None
    lens: str | None = None
    tags: str | None = None
    scene: str | None = None
    location: str | None = None
    people: str | None = None
    rights: str | None = None
    rating: int | None = None
    favorite: int = 0
    youtube_status: str | None = None
    notes: str | None = None
    status: str = "cataloged"
    telegram_chat: str | None = None
    telegram_message_id: int | None = None
    telegram_link: str | None = None
    uploaded_at: str | None = None
    downloaded_path: str | None = None
    downloaded_at: str | None = None
    completed_at: str | None = None
    remote_deleted_at: str | None = None
    thumbnail_path: str | None = None
    lossless: int | None = None


class VaultDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                filename TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                content_sha256 TEXT,
                asset_kind TEXT NOT NULL DEFAULT 'original',
                duration_seconds REAL,
                width INTEGER,
                height INTEGER,
                codec TEXT,
                project TEXT,
                shoot_date TEXT,
                camera TEXT,
                lens TEXT,
                tags TEXT,
                scene TEXT,
                location TEXT,
                people TEXT,
                rights TEXT,
                rating INTEGER,
                favorite INTEGER NOT NULL DEFAULT 0,
                youtube_status TEXT,
                notes TEXT,
                status TEXT NOT NULL,
                telegram_chat TEXT,
                telegram_message_id INTEGER,
                telegram_link TEXT,
                uploaded_at TEXT,
                downloaded_path TEXT,
                downloaded_at TEXT,
                completed_at TEXT,
                remote_deleted_at TEXT,
                thumbnail_path TEXT,
                lossless INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS download_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL UNIQUE,
                note TEXT,
                added_at TEXT NOT NULL,
                FOREIGN KEY (sha256) REFERENCES assets(sha256) ON DELETE CASCADE
            )
            """
        )
        self._ensure_columns()
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_tags ON assets(tags)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_shoot_date ON assets(shoot_date)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_asset_kind ON assets(asset_kind)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_added_at ON download_queue(added_at)")
        self.conn.commit()

    def _ensure_columns(self) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(assets)").fetchall()
        }
        migrations = {
            "asset_kind": "ALTER TABLE assets ADD COLUMN asset_kind TEXT NOT NULL DEFAULT 'original'",
            "content_sha256": "ALTER TABLE assets ADD COLUMN content_sha256 TEXT",
            "scene": "ALTER TABLE assets ADD COLUMN scene TEXT",
            "location": "ALTER TABLE assets ADD COLUMN location TEXT",
            "people": "ALTER TABLE assets ADD COLUMN people TEXT",
            "rights": "ALTER TABLE assets ADD COLUMN rights TEXT",
            "rating": "ALTER TABLE assets ADD COLUMN rating INTEGER",
            "favorite": "ALTER TABLE assets ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0",
            "youtube_status": "ALTER TABLE assets ADD COLUMN youtube_status TEXT",
            "downloaded_path": "ALTER TABLE assets ADD COLUMN downloaded_path TEXT",
            "downloaded_at": "ALTER TABLE assets ADD COLUMN downloaded_at TEXT",
            "completed_at": "ALTER TABLE assets ADD COLUMN completed_at TEXT",
            "remote_deleted_at": "ALTER TABLE assets ADD COLUMN remote_deleted_at TEXT",
            "thumbnail_path": "ALTER TABLE assets ADD COLUMN thumbnail_path TEXT",
            "lossless": "ALTER TABLE assets ADD COLUMN lossless INTEGER",
        }
        for column, sql in migrations.items():
            if column not in existing:
                self.conn.execute(sql)

    def upsert_asset(self, asset: Asset) -> sqlite3.Row:
        now = utc_now()
        payload = asdict(asset)
        payload["created_at"] = now
        payload["updated_at"] = now
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(f":{key}" for key in payload)
        preserve_existing = {
            "sha256",
            "created_at",
            "content_sha256",
            "status",
            "telegram_message_id",
            "telegram_link",
            "uploaded_at",
            "downloaded_path",
            "downloaded_at",
            "completed_at",
            "remote_deleted_at",
            "favorite",
        }
        fill_when_empty = {
            "asset_kind",
            "duration_seconds",
            "width",
            "height",
            "codec",
            "project",
            "shoot_date",
            "camera",
            "lens",
            "tags",
            "scene",
            "location",
            "people",
            "rights",
            "rating",
            "youtube_status",
            "notes",
            "thumbnail_path",
        }
        update_parts = []
        for key in payload:
            if key in preserve_existing:
                continue
            if key in fill_when_empty:
                update_parts.append(f"{key}=COALESCE(NULLIF({key}, ''), excluded.{key})")
            else:
                update_parts.append(f"{key}=excluded.{key}")
        updates = ", ".join(update_parts)
        sql = f"""
            INSERT INTO assets ({columns})
            VALUES ({placeholders})
            ON CONFLICT(sha256) DO UPDATE SET
                {updates},
                updated_at=excluded.updated_at
            RETURNING *
        """
        row = self.conn.execute(sql, payload).fetchone()
        self.conn.commit()
        return row

    def find_by_sha256(self, sha256: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM assets WHERE sha256 = ?", (sha256,)).fetchone()

    def mark_uploaded(self, sha256: str, *, chat: str, message_id: int, link: str | None) -> sqlite3.Row:
        row = self.conn.execute(
            """
            UPDATE assets
            SET status = 'uploaded',
                telegram_chat = ?,
                telegram_message_id = ?,
                telegram_link = ?,
                uploaded_at = ?,
                updated_at = ?
            WHERE sha256 = ?
            RETURNING *
            """,
            (chat, message_id, link, utc_now(), utc_now(), sha256),
        ).fetchone()
        self.conn.commit()
        return row

    def mark_downloaded(
        self,
        sha256: str,
        *,
        downloaded_path: str,
        content_sha256: str,
    ) -> sqlite3.Row:
        row = self.conn.execute(
            """
            UPDATE assets
            SET status = 'downloaded',
                downloaded_path = ?,
                content_sha256 = ?,
                downloaded_at = ?,
                updated_at = ?
            WHERE sha256 = ?
            RETURNING *
            """,
            (downloaded_path, content_sha256, utc_now(), utc_now(), sha256),
        ).fetchone()
        self.conn.commit()
        return row

    def set_thumbnail_path(self, sha256: str, thumbnail_path: str) -> sqlite3.Row:
        row = self.conn.execute(
            """
            UPDATE assets
            SET thumbnail_path = ?,
                updated_at = ?
            WHERE sha256 = ?
            RETURNING *
            """,
            (thumbnail_path, utc_now(), sha256),
        ).fetchone()
        self.conn.commit()
        return row

    def mark_done(self, sha256: str, *, notes: str | None = None) -> sqlite3.Row:
        current = self.find_by_sha256(sha256)
        merged_notes = current["notes"] if current else None
        if notes:
            merged_notes = f"{merged_notes}\nDONE: {notes}" if merged_notes else f"DONE: {notes}"
        row = self.conn.execute(
            """
            UPDATE assets
            SET status = 'done',
                notes = ?,
                completed_at = ?,
                updated_at = ?
            WHERE sha256 = ?
            RETURNING *
            """,
            (merged_notes, utc_now(), utc_now(), sha256),
        ).fetchone()
        self.conn.commit()
        return row

    def clear_downloaded_path(self, sha256: str) -> sqlite3.Row:
        row = self.conn.execute(
            """
            UPDATE assets
            SET downloaded_path = NULL,
                downloaded_at = NULL,
                updated_at = ?
            WHERE sha256 = ?
            RETURNING *
            """,
            (utc_now(), sha256),
        ).fetchone()
        self.conn.commit()
        return row

    def mark_remote_deleted(self, sha256: str) -> sqlite3.Row:
        row = self.conn.execute(
            """
            UPDATE assets
            SET status = 'remote-deleted',
                remote_deleted_at = ?,
                updated_at = ?
            WHERE sha256 = ?
            RETURNING *
            """,
            (utc_now(), utc_now(), sha256),
        ).fetchone()
        self.conn.commit()
        return row

    def list_assets(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM assets ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def search(self, query: str, limit: int = 50) -> list[sqlite3.Row]:
        pattern = f"%{query}%"
        return self.conn.execute(
            """
            SELECT * FROM assets
            WHERE filename LIKE ?
               OR project LIKE ?
               OR tags LIKE ?
               OR notes LIKE ?
               OR camera LIKE ?
               OR lens LIKE ?
               OR scene LIKE ?
               OR location LIKE ?
               OR people LIKE ?
               OR youtube_status LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, limit),
        ).fetchall()

    def all_assets(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM assets ORDER BY created_at ASC").fetchall()

    def assets_for_filters(
        self,
        *,
        query: str | None = None,
        sha_values: list[str] | None = None,
        projects: list[str] | None = None,
        statuses: list[str] | None = None,
        tags: list[str] | None = None,
        remote_only: bool = False,
        include_deleted: bool = False,
        limit: int | None = 500,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[object] = []

        if query:
            pattern = f"%{query}%"
            clauses.append(
                """
                (
                    sha256 = ?
                    OR content_sha256 = ?
                    OR filename LIKE ?
                    OR project LIKE ?
                    OR tags LIKE ?
                    OR notes LIKE ?
                    OR camera LIKE ?
                    OR lens LIKE ?
                    OR scene LIKE ?
                    OR location LIKE ?
                    OR people LIKE ?
                    OR rights LIKE ?
                    OR youtube_status LIKE ?
                )
                """
            )
            params.extend([query, query, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern])

        if sha_values:
            placeholders = ", ".join("?" for _ in sha_values)
            clauses.append(f"sha256 IN ({placeholders})")
            params.extend(sha_values)

        if projects:
            placeholders = ", ".join("?" for _ in projects)
            clauses.append(f"project IN ({placeholders})")
            params.extend(projects)

        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)

        if tags:
            tag_clauses = []
            for tag in tags:
                tag_clauses.append("tags LIKE ?")
                params.append(f"%{tag}%")
            clauses.append("(" + " OR ".join(tag_clauses) + ")")

        if remote_only:
            clauses.append("telegram_message_id IS NOT NULL")

        if not include_deleted:
            clauses.append("status != 'remote-deleted'")

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT * FROM assets
            {where}
            ORDER BY COALESCE(project, ''), COALESCE(shoot_date, uploaded_at, created_at), filename
        """
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def remote_assets_for_query(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        return self.assets_for_filters(
            query=query,
            remote_only=True,
            include_deleted=False,
            limit=limit,
        )

    _METADATA_FIELDS = {
        "asset_kind",
        "project",
        "shoot_date",
        "camera",
        "lens",
        "tags",
        "scene",
        "location",
        "people",
        "rights",
        "rating",
        "favorite",
        "youtube_status",
        "notes",
    }

    def update_metadata(self, sha_values: list[str], updates: dict[str, object | None]) -> list[sqlite3.Row]:
        if not sha_values:
            return []
        invalid = set(updates) - self._METADATA_FIELDS
        if invalid:
            raise ValueError(f"unsupported metadata fields: {', '.join(sorted(invalid))}")
        if not updates:
            placeholders = ", ".join("?" for _ in sha_values)
            return self.conn.execute(
                f"SELECT * FROM assets WHERE sha256 IN ({placeholders}) ORDER BY updated_at DESC",
                sha_values,
            ).fetchall()

        assignments = [f"{field} = ?" for field in updates]
        params = list(updates.values())
        params.append(utc_now())
        params.extend(sha_values)
        placeholders = ", ".join("?" for _ in sha_values)
        rows = self.conn.execute(
            f"""
            UPDATE assets
            SET {", ".join(assignments)},
                updated_at = ?
            WHERE sha256 IN ({placeholders})
            RETURNING *
            """,
            params,
        ).fetchall()
        self.conn.commit()
        return rows

    def first_asset_for_query(self, query: str) -> sqlite3.Row | None:
        rows = self.search(query, limit=1)
        if rows:
            return rows[0]
        return self.find_by_sha256(query)

    def add_to_queue(self, sha_values: list[str], *, note: str | None = None) -> list[sqlite3.Row]:
        now = utc_now()
        for sha256 in sha_values:
            self.conn.execute(
                """
                INSERT INTO download_queue (sha256, note, added_at)
                VALUES (?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    note = COALESCE(excluded.note, download_queue.note),
                    added_at = excluded.added_at
                """,
                (sha256, note, now),
            )
        self.conn.commit()
        return self.queued_assets()

    def remove_from_queue(self, sha_values: list[str]) -> int:
        if not sha_values:
            return 0
        placeholders = ", ".join("?" for _ in sha_values)
        cursor = self.conn.execute(f"DELETE FROM download_queue WHERE sha256 IN ({placeholders})", sha_values)
        self.conn.commit()
        return int(cursor.rowcount or 0)

    def clear_queue(self) -> int:
        cursor = self.conn.execute("DELETE FROM download_queue")
        self.conn.commit()
        return int(cursor.rowcount or 0)

    def queued_assets(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT assets.*, download_queue.note AS queue_note, download_queue.added_at AS queued_at
            FROM download_queue
            JOIN assets ON assets.sha256 = download_queue.sha256
            ORDER BY download_queue.added_at ASC, assets.filename ASC
            """
        ).fetchall()

    def stats(self) -> dict[str, object]:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS total_assets,
                COALESCE(SUM(size_bytes), 0) AS total_bytes,
                COALESCE(SUM(duration_seconds), 0) AS total_duration_seconds,
                SUM(CASE WHEN status = 'uploaded' THEN 1 ELSE 0 END) AS uploaded_assets,
                SUM(CASE WHEN status = 'remote' THEN 1 ELSE 0 END) AS remote_assets,
                SUM(CASE WHEN status = 'downloaded' THEN 1 ELSE 0 END) AS downloaded_assets,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_assets,
                SUM(CASE WHEN status = 'remote-deleted' THEN 1 ELSE 0 END) AS remote_deleted_assets,
                SUM(CASE WHEN status = 'dry-run' THEN 1 ELSE 0 END) AS dry_run_assets,
                SUM(CASE WHEN status = 'cataloged' THEN 1 ELSE 0 END) AS cataloged_assets,
                SUM(CASE WHEN favorite = 1 THEN 1 ELSE 0 END) AS favorites,
                SUM(CASE WHEN project IS NULL OR tags IS NULL OR rights IS NULL THEN 1 ELSE 0 END) AS needs_metadata
            FROM assets
            """
        ).fetchone()
        projects = self.conn.execute(
            """
            SELECT
                COALESCE(project, '(no project)') AS project,
                COUNT(*) AS assets,
                COALESCE(SUM(size_bytes), 0) AS bytes,
                COALESCE(SUM(duration_seconds), 0) AS duration_seconds,
                SUM(CASE WHEN status = 'remote' THEN 1 ELSE 0 END) AS remote_assets,
                SUM(CASE WHEN status = 'downloaded' THEN 1 ELSE 0 END) AS downloaded_assets,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_assets,
                SUM(CASE WHEN status = 'remote-deleted' THEN 1 ELSE 0 END) AS remote_deleted_assets,
                SUM(CASE WHEN favorite = 1 THEN 1 ELSE 0 END) AS favorites,
                MAX(updated_at) AS updated_at
            FROM assets
            GROUP BY COALESCE(project, '(no project)')
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return {
            "total_assets": int(row["total_assets"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
            "total_duration_seconds": float(row["total_duration_seconds"] or 0),
            "uploaded_assets": int(row["uploaded_assets"] or 0),
            "remote_assets": int(row["remote_assets"] or 0),
            "downloaded_assets": int(row["downloaded_assets"] or 0),
            "done_assets": int(row["done_assets"] or 0),
            "remote_deleted_assets": int(row["remote_deleted_assets"] or 0),
            "dry_run_assets": int(row["dry_run_assets"] or 0),
            "cataloged_assets": int(row["cataloged_assets"] or 0),
            "favorites": int(row["favorites"] or 0),
            "needs_metadata": int(row["needs_metadata"] or 0),
            "cameras": self._distinct("camera"),
            "lenses": self._distinct("lens"),
            "asset_kinds": self._distinct("asset_kind"),
            "youtube_statuses": self._distinct("youtube_status"),
            "ratings": self._distinct_int("rating"),
            "projects": [dict(project) for project in projects],
        }

    _DISTINCT_ALLOWED = {"camera", "lens", "asset_kind", "youtube_status", "status", "project"}

    def _distinct(self, field: str) -> list[str]:
        if field not in self._DISTINCT_ALLOWED:
            raise ValueError(f"unsupported distinct field: {field}")
        rows = self.conn.execute(
            f"SELECT DISTINCT {field} AS v FROM assets WHERE {field} IS NOT NULL AND {field} != '' ORDER BY {field}"
        ).fetchall()
        return [str(r["v"]) for r in rows]

    def _distinct_int(self, field: str) -> list[int]:
        if field not in self._DISTINCT_ALLOWED and field != "rating":
            raise ValueError(f"unsupported distinct field: {field}")
        rows = self.conn.execute(
            f"SELECT DISTINCT {field} AS v FROM assets WHERE {field} IS NOT NULL ORDER BY {field}"
        ).fetchall()
        return [int(r["v"]) for r in rows if r["v"] is not None]

    def export(self, path: Path, fmt: Literal["csv", "json"]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [dict(row) for row in self.all_assets()]
        if fmt == "json":
            path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            return path

        with path.open("w", newline="", encoding="utf-8") as handle:
            if not rows:
                handle.write("")
                return path
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return path


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]
