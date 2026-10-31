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

    def test_repeated_header_removed_and_table_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "report.pdf"
            document = pymupdf.open()
            for _ in range(3):
                page = document.new_page()
                page.insert_text((70, 25), "Repeated header")
                page.insert_text((70, 80), "This report has readable text before the table. " * 2)
                for x in (70, 220, 370):
                    page.draw_line((x, 110), (x, 180))
                for y in (110, 145, 180):
                    page.draw_line((70, y), (370, y))
                for x, y, value in ((80, 130, "Name"), (230, 130, "Count"),
                                    (80, 165, "Books"), (230, 165, "42")):
                    page.insert_text((x, y), value)
            document.save(pdf)
            document.close()
            output, _ = convert(pdf, Path(directory) / "out", format="epub")
            with zipfile.ZipFile(output) as book:
                section = book.read("OEBPS/section-1.xhtml").decode()
                self.assertNotIn("Repeated header", section)
                self.assertEqual(section.count("<td>Books</td>"), 3)
                self.assertEqual(section.count("Books"), 3)


if __name__ == "__main__":
    unittest.main()
