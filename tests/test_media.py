from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vamos_vault.media import build_caption, format_bytes, iter_media, normalize_tags, sha256_file


class MediaTests(unittest.TestCase):
    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.00 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.00 MB")

    def test_normalize_tags(self) -> None:
        self.assertEqual(normalize_tags("B Roll, #Street, b roll"), "b-roll,street")

    def test_sha256_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.mp4"
            path.write_bytes(b"vamos")
            self.assertEqual(
                sha256_file(path),
                "06b557a84d9e50cb1eed5a963d848406a64dc2f0cfd781ef89f667abbfcf1c9b",
            )

    def test_iter_media(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "clip.mp4").write_bytes(b"")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")
            self.assertEqual([item.name for item in iter_media([root])], ["clip.mp4"])

    def test_caption_limit(self) -> None:
        caption = build_caption(
            filename="clip.mp4",
            size_bytes=10,
            sha256="a" * 64,
            notes="x" * 2000,
            limit=200,
        )
        self.assertLessEqual(len(caption), 200)
        self.assertIn("SHA256", caption)


if __name__ == "__main__":
    unittest.main()
