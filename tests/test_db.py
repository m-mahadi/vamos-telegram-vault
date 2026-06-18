from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vamos_vault.db import Asset, VaultDB


class VaultDBTests(unittest.TestCase):
    def test_upsert_and_search(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(
                    Asset(
                        path="D:/clips/clip.mp4",
                        filename="clip.mp4",
                        size_bytes=123,
                        sha256="abc",
                        project="Dhaka vlog",
                        tags="street,broll",
                        scene="opening walk",
                        rating=4,
                        favorite=1,
                    )
                )
                rows = db.search("street")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["filename"], "clip.mp4")
                self.assertEqual(rows[0]["asset_kind"], "original")
                self.assertEqual(rows[0]["rating"], 4)
            finally:
                db.close()

    def test_mark_uploaded(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(Asset(path="clip.mp4", filename="clip.mp4", size_bytes=1, sha256="abc"))
                row = db.mark_uploaded("abc", chat="me", message_id=42, link="https://t.me/c/1/42")
                self.assertEqual(row["status"], "uploaded")
                self.assertEqual(row["telegram_message_id"], 42)
            finally:
                db.close()

    def test_remote_download_and_done_lifecycle(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(
                    Asset(
                        path="telegram://me/42",
                        filename="phone.mov",
                        size_bytes=2048,
                        sha256="tg:me:42",
                        project="Phone vlog",
                        status="remote",
                        telegram_chat="me",
                        telegram_message_id=42,
                    )
                )
                rows = db.remote_assets_for_query("Phone", limit=5)
                self.assertEqual(len(rows), 1)
                downloaded = db.mark_downloaded(
                    "tg:me:42",
                    downloaded_path=str(Path(tmp) / "phone.mov"),
                    content_sha256="realhash",
                )
                self.assertEqual(downloaded["status"], "downloaded")
                self.assertEqual(downloaded["content_sha256"], "realhash")
                done = db.mark_done("tg:me:42", notes="edited into vlog 001")
                self.assertEqual(done["status"], "done")
                self.assertIn("edited into vlog 001", done["notes"])
                deleted = db.mark_remote_deleted("tg:me:42")
                self.assertEqual(deleted["status"], "remote-deleted")
            finally:
                db.close()

    def test_resync_preserves_local_metadata_and_status(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(Asset(
                    path="telegram://me/42",
                    filename="phone.mov",
                    size_bytes=2048,
                    sha256="tg:me:42",
                    project="Edited project",
                    tags="selected",
                    status="downloaded",
                    favorite=1,
                    downloaded_path=str(Path(tmp) / "phone.mov"),
                    telegram_chat="me",
                    telegram_message_id=42,
                ))
                row = db.upsert_asset(Asset(
                    path="telegram://me/42",
                    filename="phone.mov",
                    size_bytes=2048,
                    sha256="tg:me:42",
                    project="Inbox",
                    tags="phone,raw",
                    status="remote",
                    telegram_chat="me",
                    telegram_message_id=42,
                    thumbnail_path=str(Path(tmp) / "thumb.jpg"),
                ))
                self.assertEqual(row["project"], "Edited project")
                self.assertEqual(row["tags"], "selected")
                self.assertEqual(row["status"], "downloaded")
                self.assertEqual(row["favorite"], 1)
                self.assertEqual(row["telegram_message_id"], 42)
                self.assertTrue(row["thumbnail_path"].endswith("thumb.jpg"))
            finally:
                db.close()

    def test_metadata_update_and_download_queue(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(Asset(path="a.mp4", filename="a.mp4", size_bytes=10, sha256="a"))
                db.upsert_asset(Asset(path="b.mp4", filename="b.mp4", size_bytes=20, sha256="b"))
                changed = db.update_metadata(["a", "b"], {"project": "Vlog 001", "tags": "phone,raw"})
                self.assertEqual(len(changed), 2)
                queued = db.add_to_queue(["a", "b"], note="edit this")
                self.assertEqual(len(queued), 2)
                self.assertEqual(queued[0]["queue_note"], "edit this")
                self.assertEqual(db.remove_from_queue(["a"]), 1)
                self.assertEqual(len(db.queued_assets()), 1)
                self.assertEqual(db.clear_queue(), 1)
            finally:
                db.close()

    def test_clear_downloaded_path(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(Asset(
                    path="clip.mp4",
                    filename="clip.mp4",
                    size_bytes=1,
                    sha256="abc",
                    status="downloaded",
                    downloaded_path=str(Path(tmp) / "clip.mp4"),
                ))
                row = db.clear_downloaded_path("abc")
                self.assertIsNone(row["downloaded_path"])
                self.assertIsNone(row["downloaded_at"])
            finally:
                db.close()

    def test_set_thumbnail_path(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(Asset(path="clip.mp4", filename="clip.mp4", size_bytes=1, sha256="abc"))
                row = db.set_thumbnail_path("abc", str(Path(tmp) / "thumb.jpg"))
                self.assertTrue(row["thumbnail_path"].endswith("thumb.jpg"))
            finally:
                db.close()

    def test_stats(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(
                    Asset(
                        path="clip.mp4",
                        filename="clip.mp4",
                        size_bytes=1024,
                        sha256="abc",
                        project="Launch vlog",
                        duration_seconds=12.5,
                        favorite=1,
                    )
                )
                stats = db.stats()
                self.assertEqual(stats["total_assets"], 1)
                self.assertEqual(stats["total_bytes"], 1024)
                self.assertEqual(stats["favorites"], 1)
                self.assertEqual(stats["projects"][0]["project"], "Launch vlog")
            finally:
                db.close()

    def test_stats_lifecycle_and_metadata_counters(self) -> None:
        with TemporaryDirectory() as tmp:
            db = VaultDB(Path(tmp) / "vault.db")
            try:
                db.upsert_asset(Asset(
                    path="a.mp4", filename="a.mp4", size_bytes=10, sha256="a",
                    status="remote", tags="phone", camera="iPhone",
                    youtube_status="raw",
                ))
                db.upsert_asset(Asset(
                    path="b.mp4", filename="b.mp4", size_bytes=20, sha256="b",
                    status="downloaded", project="Vlog 001", camera="Sony FX30",
                    lens="18-50", rating=4, favorite=1,
                ))
                db.upsert_asset(Asset(
                    path="c.mp4", filename="c.mp4", size_bytes=30, sha256="c",
                    status="done", project="Vlog 001", tags="done", rights="owned",
                    youtube_status="published",
                ))
                db.upsert_asset(Asset(
                    path="d.mp4", filename="d.mp4", size_bytes=40, sha256="d",
                    status="remote-deleted",
                ))
                stats = db.stats()
                self.assertEqual(stats["total_assets"], 4)
                self.assertEqual(stats["remote_assets"], 1)
                self.assertEqual(stats["downloaded_assets"], 1)
                self.assertEqual(stats["done_assets"], 1)
                self.assertEqual(stats["remote_deleted_assets"], 1)
                self.assertEqual(stats["favorites"], 1)
                self.assertEqual(stats["needs_metadata"], 3)  # a, b (no rights), d
                self.assertIn("iPhone", stats["cameras"])
                self.assertIn("18-50", stats["lenses"])
                self.assertIn("original", stats["asset_kinds"])
                self.assertIn("published", stats["youtube_statuses"])
                self.assertIn(4, stats["ratings"])
                vlog = [p for p in stats["projects"] if p["project"] == "Vlog 001"][0]
                self.assertEqual(vlog["assets"], 2)
                self.assertEqual(vlog["downloaded_assets"], 1)
                self.assertEqual(vlog["done_assets"], 1)
                self.assertEqual(vlog["favorites"], 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
