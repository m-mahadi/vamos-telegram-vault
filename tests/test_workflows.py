from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from vamos_vault.db import Asset, VaultDB
from vamos_vault.workflows import create_download_package, create_remote_preview_thumbnail


class WorkflowTests(unittest.TestCase):
    def test_package_reuses_downloaded_file_and_writes_metadata_zip(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            downloaded = base / "source.mov"
            downloaded.write_bytes(b"original video bytes")
            db = VaultDB(base / ".vamos-vault" / "vault.db")
            try:
                db.upsert_asset(Asset(
                    path="telegram://me/42",
                    filename="source.mov",
                    size_bytes=downloaded.stat().st_size,
                    sha256="tg:me:42",
                    project="Vlog 001",
                    shoot_date="2026-06-17",
                    status="downloaded",
                    telegram_chat="me",
                    telegram_message_id=42,
                    downloaded_path=str(downloaded),
                ))
                rows = [dict(row) for row in db.all_assets()]
            finally:
                db.close()

            def fake_thumbnail(base_dir, row, *, source_path=None):
                thumb = base / "thumb.jpg"
                thumb.write_bytes(b"thumb")
                return str(thumb)

            with patch("vamos_vault.workflows.ensure_thumbnail_for_asset", side_effect=fake_thumbnail):
                result = create_download_package(
                    {
                        "telegram": {"target": "me"},
                        "vault": {"database": ".vamos-vault/vault.db", "max_file_bytes": 10},
                    },
                    base,
                    rows,
                    out_dir=base / "packs",
                    name="edit-pack",
                )

            self.assertTrue(result.rows[0]["thumbnail_path"].endswith("thumb.jpg"))
            packed = result.folder / "Vlog 001" / "2026-06-17" / "original" / "source.mov"
            self.assertEqual(packed.read_bytes(), b"original video bytes")
            self.assertTrue(result.metadata_csv.exists())
            self.assertTrue(result.metadata_json.exists())
            self.assertTrue(result.zip_path and result.zip_path.exists())
            with zipfile.ZipFile(result.zip_path) as archive:
                self.assertIn("Vlog 001/2026-06-17/original/source.mov", archive.namelist())
                self.assertIn("_vamos_metadata.csv", archive.namelist())


    def test_remote_preview_thumbnail_downloads_temporarily_and_deletes_source(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = VaultDB(base / ".vamos-vault" / "vault.db")
            try:
                db.upsert_asset(Asset(
                    path="telegram://me/42",
                    filename="remote.mov",
                    size_bytes=100,
                    sha256="tg:me:42",
                    status="remote",
                    telegram_chat="me",
                    telegram_message_id=42,
                ))
                row = dict(db.all_assets()[0])
            finally:
                db.close()

            def fake_download(config, base_dir, *, message_id, out_dir, filename, progress_callback=None):
                path = out_dir / filename
                path.write_bytes(b"temporary original")
                return path

            def fake_thumbnail(base_dir, row, *, source_path=None):
                self.assertTrue(Path(str(source_path)).exists())
                thumb = base / "thumb.jpg"
                thumb.write_bytes(b"thumb")
                return str(thumb)

            with patch("vamos_vault.workflows.download_file", side_effect=fake_download), patch(
                "vamos_vault.workflows.ensure_thumbnail_for_asset", side_effect=fake_thumbnail
            ):
                thumbnail = create_remote_preview_thumbnail(
                    {"telegram": {"target": "me"}, "vault": {"database": ".vamos-vault/vault.db"}},
                    base,
                    row,
                )

            self.assertTrue(str(thumbnail).endswith("thumb.jpg"))
            self.assertFalse(any((base / ".vamos-vault" / "preview-cache").glob("*")))
            db = VaultDB(base / ".vamos-vault" / "vault.db")
            try:
                updated = db.find_by_sha256("tg:me:42")
                self.assertTrue(updated["thumbnail_path"].endswith("thumb.jpg"))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
