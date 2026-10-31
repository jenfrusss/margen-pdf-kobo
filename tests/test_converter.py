import tempfile
import unittest
import zipfile
from pathlib import Path

import pymupdf

from converter import convert


class ConverterTest(unittest.TestCase):
    def test_long_pdf_splits_into_reflowable_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "book.pdf"
            document = pymupdf.open()
            for number in range(15):
                page = document.new_page()
                page.insert_text((72, 72), f"Chapter {number + 1}", fontsize=16)
                page.insert_text((72, 105), "This is selectable text for a readable electronic book. " * 3, fontsize=10)
            document.save(pdf)
            document.close()
            output, info = convert(pdf, Path(directory) / "out", format="epub")
            self.assertEqual(info["chapters"], 2)
            with zipfile.ZipFile(output) as book:
                self.assertIsNone(book.testzip())
                self.assertIn("OEBPS/section-2.xhtml", book.namelist())
                self.assertIn(b"<h2>Chapter 1</h2>", book.read("OEBPS/section-1.xhtml"))
                self.assertIn("OEBPS/cover.jpg", book.namelist())


if __name__ == "__main__":
    unittest.main()
