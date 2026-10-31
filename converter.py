"""Convert selectable-text PDFs to reflowable EPUBs, then optional Kobo KEPUBs."""
from __future__ import annotations

import html
import re
import subprocess
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from book_tools import clean_lines, ocr_lines
from epub_validation import validate_epub
from translation import LANGUAGE_PAIRS, get_translator


def _safe(text: str) -> str:
    return html.escape(text, quote=True)


def _paragraphs(page, repeated_margins=frozenset()):
    result = []
    data = page.get_text("dict", sort=True)
    tables = page.find_tables().tables
    table_rects = [pymupdf.Rect(table.bbox) for table in tables]
    sizes = Counter()
    for block in data["blocks"]:
        if block["type"] == 0:
            for line in block.get("lines", []):
                line_rect = pymupdf.Rect(line["bbox"])
                if any(rect.contains(pymupdf.Point((line_rect.x0 + line_rect.x1) / 2, (line_rect.y0 + line_rect.y1) / 2)) for rect in table_rects):
                    continue
                for span in line.get("spans", []):
                    sizes[round(span["size"], 1)] += len(span["text"].strip())
    body_size = sizes.most_common(1)[0][0] if sizes else 12
    for block in data["blocks"]:
        block_rect = pymupdf.Rect(block["bbox"])
        if block["type"] == 0:
            lines = []
            for line in block.get("lines", []):
                line_rect = pymupdf.Rect(line["bbox"])
                if any(rect.contains(pymupdf.Point((line_rect.x0 + line_rect.x1) / 2, (line_rect.y0 + line_rect.y1) / 2)) for rect in table_rects):
                    continue
                value = "".join(span["text"] for span in line.get("spans", [])).strip()
                y = line["bbox"][1]
                margin = y < page.rect.height * .07 or y > page.rect.height * .93
                if value and not (margin and (value in repeated_margins or re.fullmatch(r"[\divxlcIVXLC.\- ]{1,12}", value))):
                    lines.append(value)
            if lines:
                value = clean_lines(lines)
                biggest = max((span["size"] for line in block["lines"] for span in line.get("spans", [])), default=body_size)
                fonts = [span.get("font", "").lower() for line in block["lines"] for span in line.get("spans", [])]
                is_list = len(lines) > 1 and all(re.match(r"^(?:[•●▪*-]|\d+[.)])\s+", line) for line in lines)
                kind = "list" if is_list else ("code" if fonts and all("courier" in font or "mono" in font for font in fonts) else ("heading" if biggest >= body_size * 1.12 and len(value) <= 120 else "text"))
                result.append((block_rect.y0, kind, lines if is_list else value))
        elif block["type"] == 1 and block.get("image"):
            result.append((block_rect.y0, "image", block))
    for table in tables:
        result.append((table.bbox[1], "table", table.extract()))
    return [(kind, value) for _, kind, value in sorted(result, key=lambda part: part[0])]


def _repeated_margins(doc):
    counts = Counter()
    for page in doc:
        seen = set()
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block.get("lines", []):
                value = "".join(span["text"] for span in line.get("spans", [])).strip()
                y = line["bbox"][1]
                if value and (y < page.rect.height * .07 or y > page.rect.height * .93):
                    seen.add(value)
        counts.update(seen)
    return {value for value, count in counts.items() if count >= max(3, doc.page_count * .3)}


def _make_cover(title: str, author: str) -> bytes:
    """Create a simple book cover, without embedding a fixed PDF page."""
    cover = pymupdf.open()
    page = cover.new_page(width=900, height=1200)
    page.draw_rect(page.rect, color=None, fill=(0.78, 0.88, 0.79))
    page.draw_line((85, 125), (815, 125), color=(0.12, 0.31, 0.25), width=3)
    title_rect = pymupdf.Rect(85, 260, 815, 850)
    for size in (64, 58, 50, 42, 34, 28):
        if page.insert_textbox(title_rect, title, fontsize=size, fontname="helv", color=(0.08, 0.22, 0.18)) >= 0:
            break
    page.insert_textbox(pymupdf.Rect(85, 930, 815, 1080), author, fontsize=28, fontname="helv", color=(0.18, 0.36, 0.29))
    result = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False).tobytes("jpeg")
    cover.close()
    return result


def convert(pdf_path: Path, output_dir: Path, title: str = "", author: str = "", keep_images: bool = True, cover: bool = True, chapters: bool = True, format: str = "kepub", kepubify: Path | None = None, translation: str = "none", ocr: bool = True, overrides=None, progress=None, cancelled=None):
    overrides = overrides or {}
    translator = get_translator(translation)
    custom_title = bool(title.strip())
    doc = pymupdf.open(pdf_path)
    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise ValueError("El PDF está protegido con contraseña.")
        if not doc.page_count:
            raise ValueError("El PDF no contiene páginas.")
        title = title.strip() or str(doc.metadata.get("title") or "").strip() or pdf_path.stem
        if translator and not custom_title:
            title = translator.translate(title)
        author = author.strip() or str(doc.metadata.get("author") or "").strip() or "Autor desconocido"
        toc = doc.get_toc() if chapters else []
        chapter_by_page = {max(0, page - 1): name for level, name, page in toc if level == 1 and 1 <= page <= doc.page_count}
        if translator:
            chapter_by_page = {page: translator.translate(name) for page, name in chapter_by_page.items()}
        if not chapter_by_page:
            chapter_by_page = {0: title}
        pages = []
        page_headings = []
        images = []
        count = 0
        ocr_count = 0
        repeated_margins = _repeated_margins(doc)
        for i, page in enumerate(doc):
            if cancelled and cancelled.is_set():
                raise InterruptedError("Conversión cancelada.")
            if progress:
                progress(i, doc.page_count, "Extrayendo texto")
            parts = []
            headings = []
            extracted = _paragraphs(page, repeated_margins)
            replacement = overrides.get("pages", {}).get(str(i + 1))
            if isinstance(replacement, str) and replacement.strip():
                extracted = [("text", paragraph.strip()) for paragraph in replacement.split("\n\n") if paragraph.strip()] + [part for part in extracted if part[0] == "image"]
            elif ocr and sum(len(value) for kind, value in extracted if kind in ("text", "heading", "code")) < 30:
                lines = ocr_lines(page)
                if lines:
                    extracted = [("text", clean_lines(lines))]
                    ocr_count += 1
            for kind, value in extracted:
                if kind in ("text", "heading", "code"):
                    if len(value.strip()) > 1:
                        count += len(value)
                        translated = translator.translate(value) if translator else value
                        if kind == "heading":
                            headings.append(translated)
                            parts.append(f"<h2>{_safe(translated)}</h2>")
                        elif kind == "code":
                            parts.append(f"<pre>{_safe(translated)}</pre>")
                        else:
                            parts.append(f"<p>{_safe(translated)}</p>")
                elif kind == "list":
                    items = []
                    for line in value:
                        item = re.sub(r"^(?:[•●▪*-]|\d+[.)])\s+", "", line)
                        item = translator.translate(item) if translator else item
                        count += len(item)
                        items.append(f"<li>{_safe(item)}</li>")
                    parts.append("<ul>" + "".join(items) + "</ul>")
                elif kind == "table":
                    rows = []
                    for cells in value:
                        values = [(translator.translate(str(cell)) if translator else str(cell)) if cell is not None else "" for cell in cells]
                        count += sum(len(cell) for cell in values)
                        rows.append("<tr>" + "".join(f"<td>{_safe(cell)}</td>" for cell in values) + "</tr>")
                    parts.append("<table>" + "".join(rows) + "</table>")
                elif keep_images and len(value["image"]) < 8_000_000:
                    ext = value.get("ext", "png").lower()
                    if ext not in ("png", "jpg", "jpeg", "gif"):
                        continue
                    name = f"image-{len(images)+1}.{ext}"
                    images.append((name, value["image"], "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"))
                    parts.append(f'<figure><img src="images/{name}" alt="Imagen de la página {i+1}"/></figure>')
            pages.append(parts)
            page_headings.append(headings)
        if count < max(40, doc.page_count * 8):
            raise ValueError("No se obtuvo texto suficiente del PDF. Revisa la vista previa y el OCR.")
        cover_bytes = _make_cover(title, author) if cover else None
    finally:
        doc.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w .()-]", "", pdf_path.stem, flags=re.UNICODE).strip() or "libro"
    epub_path = output_dir / f"{stem}.epub"
    uid = str(uuid.uuid4())
    sections = []
    current = None
    section_start = 0
    for index, parts in enumerate(pages):
        if current is None or index in chapter_by_page or index - section_start >= 12:
            section_start = index
            section_title = chapter_by_page.get(index) or (page_headings[index][0] if page_headings[index] else f"Páginas {index+1}–{min(index+12, len(pages))}")
            current = {"title": section_title, "parts": [], "start_page": index + 1}
            sections.append(current)
        current["parts"].extend(parts)
    for section in sections:
        page = section.get("start_page")
        if page and str(page) in overrides.get("sections", {}):
            section["title"] = overrides["sections"][str(page)][:120]
    css = "body{font-family:serif;line-height:1.5;margin:5%}h1{font-size:1.5em;line-height:1.2}h2{font-size:1.2em;line-height:1.25;margin:1.2em 0 .5em}p{margin:0 0 .8em;text-align:left}pre{font:0.85em monospace;white-space:pre-wrap}table{border-collapse:collapse;width:100%;font-size:.9em}td{border:1px solid #888;padding:.25em}li{margin-bottom:.35em}img{max-width:100%;height:auto}figure{margin:1em 0;text-align:center}"
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>', '<item id="style" href="style.css" media-type="text/css"/>']
    spine = []
    for n, _ in enumerate(sections, 1):
        manifest.append(f'<item id="s{n}" href="section-{n}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="s{n}"/>')
    for n, (name, _, mime) in enumerate(images, 1):
        manifest.append(f'<item id="i{n}" href="images/{name}" media-type="{mime}"/>')
    if cover_bytes:
        manifest.append('<item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>')
        manifest.append('<item id="coverpage" href="cover.xhtml" media-type="application/xhtml+xml"/>')
        spine.insert(0, '<itemref idref="coverpage"/>')
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output_language = LANGUAGE_PAIRS[translation][1] if translation != "none" else "es"
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="{output_language}"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">urn:uuid:{uid}</dc:identifier><dc:title>{_safe(title)}</dc:title><dc:creator>{_safe(author)}</dc:creator><dc:language>{output_language}</dc:language><meta property="dcterms:modified">{modified}</meta></metadata><manifest>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>'''
    nav_items = ''.join(f'<li><a href="section-{n}.xhtml">{_safe(s["title"])}</a></li>' for n, s in enumerate(sections, 1))
    nav = f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Índice</title></head><body><nav epub:type="toc" id="toc"><h1>Índice</h1><ol>{nav_items}</ol></nav></body></html>'
    with zipfile.ZipFile(epub_path, "w") as book:
        if cancelled and cancelled.is_set():
            raise InterruptedError("Conversión cancelada.")
        if progress:
            progress(len(pages), len(pages), "Creando EPUB")
        book.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        book.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        book.writestr("OEBPS/content.opf", opf)
        book.writestr("OEBPS/nav.xhtml", nav)
        book.writestr("OEBPS/style.css", css)
        if cover_bytes:
            book.writestr("OEBPS/cover.jpg", cover_bytes)
            book.writestr("OEBPS/cover.xhtml", '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Portada</title></head><body><div><img src="cover.jpg" alt="Portada" style="max-width:100%"/></div></body></html>')
        for name, data, _ in images:
            book.writestr(f"OEBPS/images/{name}", data)
        for n, section in enumerate(sections, 1):
            body = f'<h1>{_safe(section["title"])}</h1>' + "".join(section["parts"])
            xhtml = f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{_safe(section["title"])}</title><link rel="stylesheet" href="style.css" type="text/css"/></head><body>{body}</body></html>'
            book.writestr(f"OEBPS/section-{n}.xhtml", xhtml)
    if progress:
        progress(len(pages), len(pages), "Validando EPUB")
    validation = validate_epub(epub_path, Path(__file__).resolve().parent)
    if format == "kepub":
        if cancelled and cancelled.is_set():
            raise InterruptedError("Conversión cancelada.")
        if progress:
            progress(len(pages), len(pages), "Creando KEPUB")
        if not kepubify or not kepubify.exists():
            raise RuntimeError("Falta kepubify. Ejecuta instalar.ps1 para habilitar KEPUB.")
        kepub_path = output_dir / f"{stem}.kepub.epub"
        result = subprocess.run([str(kepubify), "-o", str(kepub_path), str(epub_path)], capture_output=True, text=True, timeout=120)
        if result.returncode or not kepub_path.exists():
            raise RuntimeError(f"KEPUB no se pudo generar: {result.stderr or result.stdout}")
        validate_epub(kepub_path, Path(__file__).resolve().parent)
        return kepub_path, {"title": title, "pages": len(pages), "chapters": len(sections), "images": len(images), "ocr_pages": ocr_count, "validation": validation}
    return epub_path, {"title": title, "pages": len(pages), "chapters": len(sections), "images": len(images), "ocr_pages": ocr_count, "validation": validation}
