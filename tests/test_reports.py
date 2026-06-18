from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vamos_vault.reports import build_manifest, enrich_assets_for_display, write_studio_html


class ReportsTests(unittest.TestCase):
    def test_manifest_shape(self) -> None:
        config = {
            "telegram": {"target": "me"},
            "vault": {"send_as_document": True, "max_file_bytes": 10},
        }
        stats = {
            "total_assets": 1,
            "uploaded_assets": 0,
            "total_bytes": 10,
            "total_duration_seconds": 2,
            "favorites": 0,
            "projects": [],
        }
        manifest = build_manifest(config=config, stats=stats, assets=[{"filename": "clip.mp4"}])
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["telegram"]["target"], "me")
        self.assertEqual(manifest["telegram"]["upload_mode"], "original_document")
        self.assertTrue(manifest["telegram"]["send_as_document"])
        self.assertEqual(manifest["assets"][0]["filename"], "clip.mp4")

    def test_studio_html_contains_embedded_assets(self) -> None:
        config = {
            "telegram": {"target": "me"},
            "vault": {"send_as_document": True, "max_file_bytes": 10},
        }
        assets = enrich_assets_for_display(
            [{"filename": "clip.mp4", "size_bytes": 10, "duration_seconds": 2, "status": "dry-run"}]
        )
        stats = {
            "total_assets": 1,
            "uploaded_assets": 0,
            "remote_assets": 0,
            "downloaded_assets": 0,
            "done_assets": 0,
            "remote_deleted_assets": 0,
            "dry_run_assets": 1,
            "favorites": 0,
            "needs_metadata": 0,
            "total_bytes": 10,
            "total_duration_seconds": 2,
            "cameras": [],
            "lenses": [],
            "asset_kinds": [],
            "youtube_statuses": [],
            "ratings": [],
            "projects": [],
        }
        manifest = build_manifest(config=config, stats=stats, assets=assets)
        with TemporaryDirectory() as tmp:
            path = write_studio_html(Path(tmp) / "studio.html", manifest)
            html = path.read_text(encoding="utf-8")
            self.assertIn("Vamos Telegram Vault Studio", html)
            self.assertIn("clip.mp4", html)
            self.assertIn("Preview", html)
            self.assertNotIn('""":"&quot;"', html)

    def test_enrich_assets_adds_thumbnail_uri(self) -> None:
        with TemporaryDirectory() as tmp:
            thumb = Path(tmp) / "thumb.jpg"
            thumb.write_bytes(b"fake")
            assets = enrich_assets_for_display(
                [{"filename": "clip.mp4", "size_bytes": 10, "thumbnail_path": str(thumb)}]
            )
            self.assertTrue(assets[0]["thumbnail_uri"].startswith("file:///"))

    def test_enrich_assets_preserves_all_rows(self) -> None:
        assets = enrich_assets_for_display(
            [
                {"filename": "clip-a.mp4", "size_bytes": 10},
                {"filename": "clip-b.mp4", "size_bytes": 20},
            ]
        )
        self.assertEqual(["clip-a.mp4", "clip-b.mp4"], [asset["filename"] for asset in assets])

    def test_studio_html_has_quick_filters_and_cli_snippets(self) -> None:
        config = {
            "telegram": {"target": "@vault"},
            "vault": {"send_as_document": True, "max_file_bytes": 10},
        }
        assets = enrich_assets_for_display([
            {
                "filename": "phone.mov", "size_bytes": 1024, "duration_seconds": 5,
                "status": "remote", "sha256": "tg:me:42", "project": "Vlog 001",
                "tags": "phone,raw", "camera": "iPhone", "favorite": 1,
                "telegram_link": "https://t.me/c/1/42",
            }
        ])
        stats = {
            "total_assets": 1,
            "uploaded_assets": 0,
            "remote_assets": 1,
            "downloaded_assets": 0,
            "done_assets": 0,
            "remote_deleted_assets": 0,
            "dry_run_assets": 0,
            "favorites": 1,
            "needs_metadata": 1,
            "total_bytes": 1024,
            "total_duration_seconds": 5,
            "cameras": ["iPhone"],
            "lenses": [],
            "asset_kinds": ["original"],
            "youtube_statuses": ["raw"],
            "ratings": [],
            "projects": [],
        }
        manifest = build_manifest(config=config, stats=stats, assets=assets)
        with TemporaryDirectory() as tmp:
            path = write_studio_html(Path(tmp) / "studio.html", manifest)
            html = path.read_text(encoding="utf-8")
            for label in ["Remote archive", "Ready to edit", "Done", "Favorites", "Needs metadata", "Remote-deleted"]:
                self.assertIn(label, html)
            self.assertIn("vamos-vault studio --open", html)
            self.assertIn("vamos-vault download", html)
            self.assertIn("--delete-remote --yes", html)
            self.assertIn("tg:me:42", html)
            self.assertNotIn('""":"&quot;"', html)


if __name__ == "__main__":
    unittest.main()
