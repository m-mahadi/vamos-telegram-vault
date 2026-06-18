from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from vamos_vault.thumbnails import ensure_thumbnail_for_asset, is_video_asset


class ThumbnailTests(unittest.TestCase):
    def test_image_thumbnail_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "still.png"
            Image.new("RGB", (1200, 800), color=(10, 20, 30)).save(source)
            row = {"filename": "still.png", "sha256": "abc", "codec": "image/png"}
            thumbnail = ensure_thumbnail_for_asset(base, row, source_path=source)
            self.assertIsNotNone(thumbnail)
            self.assertTrue(Path(str(thumbnail)).exists())
            self.assertTrue(str(thumbnail).endswith(".jpg"))

    def test_video_detection_by_codec_and_suffix(self) -> None:
        self.assertTrue(is_video_asset({"filename": "clip.mov"}))
        self.assertTrue(is_video_asset({"codec": "video/webm"}))


if __name__ == "__main__":
    unittest.main()
