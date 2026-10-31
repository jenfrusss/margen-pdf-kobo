import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kobo_device
import app as web_app


class KoboDeviceTest(unittest.TestCase):
    def test_detect_copy_and_preserve_existing_book(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "KOBOeReader"
            (root / ".kobo").mkdir(parents=True)
            source = base / "Libro.kepub.epub"
            source.write_bytes(b"book contents")
            with patch.object(kobo_device, "_candidate_roots", return_value=[root]), patch.object(kobo_device, "_volume_label", return_value="KOBOeReader"):
                devices = kobo_device.connected_kobos()
                self.assertEqual(len(devices), 1)
                first = Path(kobo_device.copy_to_kobo(source, devices[0]["id"]))
                second = Path(kobo_device.copy_to_kobo(source, devices[0]["id"]))
                self.assertEqual(first.read_bytes(), b"book contents")
                self.assertEqual(second.read_bytes(), b"book contents")
                self.assertNotEqual(first, second)
                self.assertFalse(list(root.glob("*.part")))

    def test_rejects_disconnected_device(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Libro.epub"
            source.write_bytes(b"book")
            with patch.object(kobo_device, "connected_kobos", return_value=[]):
                with self.assertRaisesRegex(ValueError, "No se detecta"):
                    kobo_device.copy_to_kobo(source, "Z:\\")

    def test_api_requires_known_book_and_device(self):
        client = web_app.app.test_client()
        with patch.object(web_app, "connected_kobos", return_value=[]):
            self.assertEqual(client.get("/devices").json, {"devices": []})
        response = client.post("/send-to-kobo", json={"job": "../outside", "filename": "book.epub", "device": "E:\\"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
