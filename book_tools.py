"""PDF diagnostics, local OCR, and text cleanup for the conversion workflow."""
from __future__ import annotations

import re
from pathlib import Path
from threading import Lock

import pymupdf

_engine = None
_ocr_lock = Lock()


def ocr_lines(page):
    global _engine
    image = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
    with _ocr_lock:
        if _engine is None:
            from rapidocr import ModelType, OCRVersion, RapidOCR
            _engine = RapidOCR(params={"Rec.lang_type": "latin", "Rec.ocr_version": OCRVersion.PPOCRV5,
                                       "Rec.model_type": ModelType.MOBILE})
        result = _engine(image)
    return [line.strip() for line in (result.txts or ()) if line.strip()]


def clean_lines(lines):
    result = ""
    for line in lines:
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if result.endswith("-") and line[:1].islower():
            result = result[:-1] + line
        else:
            result += (" " if result else "") + line
    return result.strip()


def analyze_pdf(path: Path, sample_pages: int = 3):
    doc = pymupdf.open(path)
    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise ValueError("El PDF está protegido con contraseña.")
        if not len(doc):
            raise ValueError("El PDF no contiene páginas.")
        samples, scanned, images, columns, tables = [], 0, 0, 0, 0
        toc = {page - 1: title for level, title, page in doc.get_toc()
               if level == 1 and 1 <= page <= len(doc)}
        headings = []
        for index, page in enumerate(doc):
            text = page.get_text("text", sort=True)
            if len(text.strip()) < 30:
                scanned += 1
            blocks = page.get_text("blocks", sort=True)
            images += sum(1 for block in blocks if len(block) > 6 and block[6] == 1)
            tables += len(page.find_tables().tables)
            text_blocks = [block for block in blocks if len(block) > 6 and block[6] == 0]
            left = sum(1 for block in text_blocks if block[2] < page.rect.width * .55)
            right = sum(1 for block in text_blocks if block[0] > page.rect.width * .45)
            if left > 2 and right > 2:
                columns += 1
            if index < sample_pages:
                is_scanned = len(text.strip()) < 30
                sample = clean_lines(ocr_lines(page)) if is_scanned else text[:4000]
                samples.append({"page": index + 1, "text": sample, "scanned": is_scanned})
            if index == 0 or index in toc or index - (headings[-1]["page"] - 1) >= 12:
                headings.append({"page": index + 1, "title": toc.get(index) or
                                 (str(doc.metadata.get("title") or "").strip() or path.stem if index == 0
                                  else f"Páginas {index+1}–{min(index+12, len(doc))}")})
        return {"pages": len(doc), "scanned_pages": scanned, "image_blocks": images, "tables": tables,
                "possible_columns": columns, "samples": samples, "sections": headings,
                "title": str(doc.metadata.get("title") or "").strip() or path.stem,
                "author": str(doc.metadata.get("author") or "").strip()}
    finally:
        doc.close()
