"""Validate generated EPUB containers, with EPUBCheck when installed."""
from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def validate_epub(path: Path, base: Path) -> str:
    with zipfile.ZipFile(path) as book:
        names = set(book.namelist())
        if book.testzip() is not None or not book.infolist() or book.infolist()[0].filename != "mimetype":
            raise ValueError("El EPUB generado no es un archivo ZIP válido.")
        if book.read("mimetype") != b"application/epub+zip":
            raise ValueError("El EPUB tiene un tipo de archivo incorrecto.")
        if "META-INF/container.xml" not in names:
            raise ValueError("Falta el contenedor del EPUB.")
        container = ET.fromstring(book.read("META-INF/container.xml"))
        rootfile = container.find(".//{*}rootfile")
        if rootfile is None:
            raise ValueError("Falta el archivo principal del EPUB.")
        opf_name = rootfile.attrib["full-path"]
        opf = ET.fromstring(book.read(opf_name))
        prefix = str(Path(opf_name).parent).replace("\\", "/")
        manifest = opf.find("{*}manifest")
        spine = opf.find("{*}spine")
        if manifest is None or spine is None:
            raise ValueError("Faltan secciones del EPUB.")
        ids = set()
        for item in manifest:
            ids.add(item.attrib["id"])
            name = f"{prefix}/{item.attrib['href']}" if prefix != "." else item.attrib["href"]
            if name not in names:
                raise ValueError(f"Falta un archivo del EPUB: {name}")
            if name.endswith((".xhtml", ".opf")):
                ET.fromstring(book.read(name))
        if not list(spine) or any(item.attrib.get("idref") not in ids for item in spine):
            raise ValueError("El orden de lectura del EPUB es inválido.")
    java = next((p for p in (base / "tools" / "jre").glob("**/bin/java.exe") if p.is_file()), None)
    jar = next((p for p in (base / "tools" / "epubcheck").glob("**/epubcheck.jar") if p.is_file()), None)
    if java and jar:
        result = subprocess.run([str(java), "-jar", str(jar), str(path)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            detail = (result.stderr + "\n" + result.stdout).strip()[-1200:]
            raise ValueError("EPUBCheck detectó errores: " + detail)
        return "EPUBCheck"
    return "Estructura EPUB"
