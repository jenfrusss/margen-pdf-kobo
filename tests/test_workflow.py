import io
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pymupdf

import app as margen


class WorkflowTest(unittest.TestCase):
    def test_review_edit_convert_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = pymupdf.open()
            for _ in range(3):
                page = document.new_page()
                page.insert_text((70, 100), "Original chapter text in a readable PDF document. " * 3)
            source = root / "book.pdf"
            document.save(source)
            document.close()
            with patch.object(margen, "UPLOADS", root / "uploads"), patch.object(margen, "OUTPUTS", root / "outputs"):
                margen.JOBS.clear()
                client = margen.app.test_client()
                review = client.post("/analyze", data={"file": (io.BytesIO(source.read_bytes()), "book.pdf")})
                self.assertEqual(review.status_code, 200)
                data = review.get_json()
                self.assertEqual(data["scanned_pages"], 0)
                self.assertIn("Original chapter", data["samples"][0]["text"])
                start = client.post("/start", json={"token": data["token"], "filename": data["filename"],
                                                    "options": {"format": "epub", "translation": "none", "ocr": True},
                                                    "overrides": {"pages": {"1": "Edited text that will appear in the finished electronic book."},
                                                                  "breaks": [{"page": 1, "title": "Edited chapter"},
                                                                             {"page": 2, "title": "New chapter break"}]}})
                self.assertEqual(start.status_code, 202)
                job = start.get_json()["job"]
                for _ in range(100):
                    state = client.get(f"/jobs/{job}").get_json()
                    if state["status"] != "running":
                        break
                    time.sleep(.1)
                self.assertEqual(state["status"], "done", state.get("error"))
                self.assertIn(state["validation"], ("EPUBCheck", "Estructura EPUB"))
                with zipfile.ZipFile(root / "outputs" / job / state["filename"]) as book:
                    section = book.read("OEBPS/section-1.xhtml").decode()
                    self.assertIn("Edited text", section)
                    self.assertIn("Edited chapter", section)
                    second = book.read("OEBPS/section-2.xhtml").decode()
                    self.assertIn("New chapter break", second)
                download = client.get(state["download"])
                self.assertEqual(download.status_code, 200)
                download.close()
                self.assertEqual(client.get("/history").get_json()["jobs"][0]["job"], job)
                margen.JOBS.clear()


if __name__ == "__main__":
    unittest.main()
