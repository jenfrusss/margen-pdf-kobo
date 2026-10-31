"""Find mounted Kobo readers and copy finished books to their root directory."""
from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


def _candidate_roots():
    if sys.platform == "win32":
        kernel = ctypes.windll.kernel32
        drives = kernel.GetLogicalDrives()
        for number in range(26):
            if drives & (1 << number):
                root = Path(f"{chr(65 + number)}:\\")
                if kernel.GetDriveTypeW(str(root)) in (2, 3):
                    yield root
    else:
        for parent in (Path("/media"), Path("/run/media"), Path("/Volumes")):
            if parent.is_dir():
                for child in parent.iterdir():
                    if child.is_dir():
                        yield child
                        if parent.name == "media":
                            yield from (item for item in child.iterdir() if item.is_dir())


def _volume_label(root: Path):
    if sys.platform != "win32":
        return root.name
    label = ctypes.create_unicode_buffer(256)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        str(root), label, len(label), None, None, None, None, 0
    )
    return label.value if ok else ""


def connected_kobos():
    devices = []
    for root in _candidate_roots():
        try:
            marker = root / ".kobo"
            label = _volume_label(root)
            if marker.is_dir() and (label.lower() == "koboereader" or (marker / "KoboReader.sqlite").is_file()):
                space = shutil.disk_usage(root)
                devices.append({"id": str(root), "label": label or "Kobo", "path": str(root),
                                "free_bytes": space.free, "total_bytes": space.total})
        except OSError:
            continue
    return devices


def kobo_library(device_id: str):
    device = next((item for item in connected_kobos() if item["id"] == device_id), None)
    if device is None:
        raise ValueError("No se detecta ese Kobo. Conéctalo por USB y toca Conectar en el lector.")
    root = Path(device["path"])
    books = []
    for path in root.iterdir():
        if path.is_file() and path.name.lower().endswith(".epub"):
            info = path.stat()
            books.append({"name": path.name, "size_bytes": info.st_size,
                          "kind": "KEPUB" if path.name.lower().endswith(".kepub.epub") else "EPUB",
                          "modified": info.st_mtime})
    books.sort(key=lambda book: book["modified"], reverse=True)
    return {"device": device, "books": books}


def _sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def copy_to_kobo(source: Path, device_id: str):
    device = next((item for item in connected_kobos() if item["id"] == device_id), None)
    if device is None:
        raise ValueError("No se detecta ese Kobo. Conéctalo por USB y toca Conectar en el lector.")
    root = Path(device["path"])
    if not source.is_file() or source.suffix.lower() != ".epub":
        raise ValueError("El libro convertido no está disponible.")
    source_hash = _sha256(source)
    suffix = ".kepub.epub" if source.name.lower().endswith(".kepub.epub") else ".epub"
    base = source.name[:-len(suffix)]
    target = root / source.name
    if target.exists():
        if target.stat().st_size == source.stat().st_size and _sha256(target) == source_hash:
            return {"path": str(target), "already_present": True}
        for index in range(2, 1000):
            target = root / f"{base} ({index}){suffix}"
            if not target.exists():
                break
            if target.stat().st_size == source.stat().st_size and _sha256(target) == source_hash:
                return {"path": str(target), "already_present": True}
        else:
            raise ValueError("Hay demasiadas copias de este libro en el Kobo.")
    if shutil.disk_usage(root).free < source.stat().st_size + 1024 * 1024:
        raise ValueError("El Kobo no tiene espacio suficiente para este libro.")
    temporary = root / f".margen-{uuid.uuid4().hex}.part"
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if temporary.stat().st_size != source.stat().st_size or _sha256(temporary) != source_hash:
            raise OSError("La copia no coincide con el libro original.")
        temporary.replace(target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return {"path": str(target), "already_present": False}


def eject_kobo(device_id: str):
    if sys.platform != "win32":
        raise RuntimeError("La expulsión desde la app está disponible en Windows.")
    device = next((item for item in connected_kobos() if item["id"] == device_id), None)
    if device is None:
        raise ValueError("No se detecta ese Kobo. Actualiza el estado del dispositivo.")
    root = Path(device["path"])
    if len(root.drive) != 2 or root.drive[1] != ":" or not root.drive[0].isalpha():
        raise ValueError("La unidad del Kobo no es válida.")
    script = (
        "$ErrorActionPreference='Stop'; "
        "$shell=New-Object -ComObject Shell.Application; "
        "$item=$shell.Namespace(17).ParseName($env:MARGEN_KOBO_DRIVE); "
        "if($null -eq $item){throw 'No se encuentra la unidad.'}; "
        "$verb=$item.Verbs() | Where-Object { ($_.Name -replace '&','').Trim() -match '^(Eject|Expulsar)$' } | Select-Object -First 1; "
        "if($null -eq $verb){throw 'Windows no ofrece la acción Expulsar para esta unidad.'}; "
        "$verb.DoIt()"
    )
    environment = os.environ.copy()
    environment["MARGEN_KOBO_DRIVE"] = root.drive
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
        capture_output=True, text=True, timeout=20, env=environment,
    )
    if result.returncode:
        raise RuntimeError("Windows no pudo expulsar el Kobo. Cierra archivos abiertos e inténtalo otra vez.")
    for _ in range(20):
        if not any(item["id"] == device_id for item in connected_kobos()):
            return
        time.sleep(0.5)
    raise RuntimeError("Windows no confirmó la expulsión. Usa «Quitar hardware de forma segura» antes de desconectarlo.")
