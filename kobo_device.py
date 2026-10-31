"""Find mounted Kobo readers and copy finished books to their root directory."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
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
    environment = os.environ.copy()
    environment["MARGEN_KOBO_LETTER"] = root.drive[0]
    script = (
        "$ErrorActionPreference='Stop'; "
        "$partition=Get-Partition -DriveLetter $env:MARGEN_KOBO_LETTER; "
        "$disk=Get-CimInstance Win32_DiskDrive -Filter ('Index=' + $partition.DiskNumber); "
        "if($null -eq $disk -or $disk.InterfaceType -ne 'USB'){throw 'El Kobo no es una unidad USB.'}; "
        "$disk.PNPDeviceID"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=25, env=environment,
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Windows no pudo identificar la unidad USB del Kobo.")
    _request_usb_eject(result.stdout.strip().splitlines()[-1])
    for _ in range(20):
        if not any(item["id"] == device_id for item in connected_kobos()):
            return
        time.sleep(0.5)
    raise RuntimeError("Windows no confirmó la expulsión. Usa «Quitar hardware de forma segura» antes de desconectarlo.")


def _request_usb_eject(disk_id: str):
    manager = ctypes.WinDLL("CfgMgr32.dll")
    locate = manager.CM_Locate_DevNodeW
    locate.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.LPWSTR, wintypes.ULONG]
    locate.restype = wintypes.ULONG
    parent = manager.CM_Get_Parent
    parent.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.ULONG, wintypes.ULONG]
    parent.restype = wintypes.ULONG
    get_id = manager.CM_Get_Device_IDW
    get_id.argtypes = [wintypes.ULONG, wintypes.LPWSTR, wintypes.ULONG, wintypes.ULONG]
    get_id.restype = wintypes.ULONG
    eject = manager.CM_Request_Device_EjectW
    eject.argtypes = [wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), wintypes.LPWSTR, wintypes.ULONG, wintypes.ULONG]
    eject.restype = wintypes.ULONG

    node = wintypes.ULONG()
    if locate(ctypes.byref(node), disk_id, 0):
        raise RuntimeError("Windows no encuentra el dispositivo USB del Kobo.")
    for _ in range(8):
        name = ctypes.create_unicode_buffer(512)
        if get_id(node, name, len(name), 0):
            raise RuntimeError("Windows no pudo comprobar el dispositivo USB.")
        if name.value.upper().startswith("USB\\VID_"):
            break
        next_node = wintypes.ULONG()
        if parent(ctypes.byref(next_node), node, 0):
            raise RuntimeError("Windows no encontró el controlador USB del Kobo.")
        node = next_node
    else:
        raise RuntimeError("Windows no encontró el dispositivo USB físico del Kobo.")
    veto = wintypes.ULONG()
    veto_name = ctypes.create_unicode_buffer(260)
    code = eject(node, ctypes.byref(veto), veto_name, len(veto_name), 0)
    if code:
        detail = veto_name.value or f"código {code}, veto {veto.value}"
        raise RuntimeError("Windows no pudo expulsar el Kobo: " + detail)
