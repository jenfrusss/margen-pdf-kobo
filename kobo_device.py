"""Find mounted Kobo readers and copy finished books to their root directory."""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
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
                devices.append({"id": str(root), "label": label or "Kobo", "path": str(root)})
        except OSError:
            continue
    return devices


def copy_to_kobo(source: Path, device_id: str):
    device = next((item for item in connected_kobos() if item["id"] == device_id), None)
    if device is None:
        raise ValueError("No se detecta ese Kobo. Conéctalo por USB y toca Conectar en el lector.")
    root = Path(device["path"])
    if not source.is_file() or source.suffix.lower() != ".epub":
        raise ValueError("El libro convertido no está disponible.")
    if shutil.disk_usage(root).free < source.stat().st_size + 1024 * 1024:
        raise ValueError("El Kobo no tiene espacio suficiente para este libro.")
    target = root / source.name
    if target.exists():
        base = source.name[:-5]
        for index in range(2, 1000):
            target = root / f"{base} ({index}).epub"
            if not target.exists():
                break
        else:
            raise ValueError("Hay demasiadas copias de este libro en el Kobo.")
    temporary = root / f".margen-{uuid.uuid4().hex}.part"
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if temporary.stat().st_size != source.stat().st_size:
            raise OSError("La copia quedó incompleta.")
        temporary.replace(target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return str(target)
