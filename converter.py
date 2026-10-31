"""Convert selectable-text PDFs to reflowable EPUBs, then optional Kobo KEPUBs."""
from __future__ import annotations

import html
import re
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pymupdf


def _safe(text: str) -> str:
    return html.escape(text, quote=True)


def _paragraphs(page):
    result = []
    data = page.get_text("dict", sort=True)
    for block in data["blocks"]:
        if block["type"] == 0:
            lines = []
            for line in block.get("lines", []):
                value = "".join(span["text"] for span in line.get("spans", [])).strip()
                if value:
                    lines.append(value)
            if lines:
                result.append(("text", " ".join(lines)))
        elif block["type"] == 1 and block.get("image"):
            result.append(("image", block))
    return result


def convert(pdf_path: Path, output_dir: Path, title: str = "", author: str = "", keep_images: bool = True, cover: bool = True, chapters: bool = True, format: str = "kepub", kepubify: Path | None = None):
    doc = pymupdf.open(pdf_path)
    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise ValueError("El PDF está protegido con contraseña.")
        if not doc.page_count:
            raise ValueError("El PDF no contiene páginas.")
        title = title.strip() or str(doc.metadata.get("title") or "").strip() or pdf_path.stem
        author = author.strip() or str(doc.metadata.get("author") or "").strip() or "Autor desconocido"
        toc = doc.get_toc() if chapters else []
        chapter_by_page = {max(0, page - 1): name for level, name, page in toc if level == 1 and 1 <= page <= doc.page_count}
        if not chapter_by_page:
            chapter_by_page = {0: title}
        pages = []
        images = []
        count = 0
        for i, page in enumerate(doc):
            parts = []
            for kind, value in _paragraphs(page):
                if kind == "text":
                    if len(value.strip()) > 1:
                        count += len(value)
                        parts.append(f"<p>{_safe(value)}</p>")
                elif keep_images and len(value["image"]) < 8_000_000:
                    ext = value.get("ext", "png").lower()
                    if ext not in ("png", "jpg", "jpeg", "gif"):
                        continue
                    name = f"image-{len(images)+1}.{ext}"
                    images.append((name, value["image"], "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"))
                    parts.append(f'<figure><img src="images/{name}" alt="Imagen de la página {i+1}"/></figure>')
            pages.append(parts)
        if count < max(40, doc.page_count * 8):
            raise ValueError("No se detectó texto seleccionable. Este PDF parece escaneado y necesita OCR.")
        cover_bytes = None
        if cover:
            pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(1.35, 1.35), alpha=False)
            cover_bytes = pix.tobytes("jpeg")
    finally:
        doc.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w .()-]", "", pdf_path.stem, flags=re.UNICODE).strip() or "libro"
    epub_path = output_dir / f"{stem}.epub"
    uid = str(uuid.uuid4())
    sections = []
    current = None
    for index, parts in enumerate(pages):
        if index in chapter_by_page or current is None:
            current = {"title": chapter_by_page.get(index, f"Página {index+1}"), "parts": []}
            sections.append(current)
        current["parts"].extend(parts)
    css = "body{font-family:serif;line-height:1.5;margin:5%}h1{font-size:1.5em;line-height:1.2}p{margin:0 0 .8em;text-align:left}img{max-width:100%;height:auto}figure{margin:1em 0;text-align:center}"
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
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="es"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">urn:uuid:{uid}</dc:identifier><dc:title>{_safe(title)}</dc:title><dc:creator>{_safe(author)}</dc:creator><dc:language>es</dc:language><meta property="dcterms:modified">{modified}</meta></metadata><manifest>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>'''
    nav_items = ''.join(f'<li><a href="section-{n}.xhtml">{_safe(s["title"])}</a></li>' for n, s in enumerate(sections, 1))
    nav = f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Índice</title></head><body><nav epub:type="toc" id="toc"><h1>Índice</h1><ol>{nav_items}</ol></nav></body></html>'
    with zipfile.ZipFile(epub_path, "w") as book:
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
    if format == "kepub":
        if not kepubify or not kepubify.exists():
            raise RuntimeError("Falta kepubify. Ejecuta instalar.ps1 para habilitar KEPUB.")
        kepub_path = output_dir / f"{stem}.kepub.epub"
        result = subprocess.run([str(kepubify), "-o", str(kepub_path), str(epub_path)], capture_output=True, text=True, timeout=120)
        if result.returncode or not kepub_path.exists():
            raise RuntimeError(f"KEPUB no se pudo generar: {result.stderr or result.stdout}")
        return kepub_path, {"title": title, "pages": len(pages), "chapters": len(sections), "images": len(images)}
    return epub_path, {"title": title, "pages": len(pages), "chapters": len(sections), "images": len(images)}
