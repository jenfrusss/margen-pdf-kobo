import tempfile
import unittest
import ctypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import kobo_device
import app as web_app


class KoboDeviceTest(unittest.TestCase):
    def test_detect_copy_and_preserve_existing_book(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "KOBOeReader"
            (root / ".kobo").mkdir(parents=True)
            source = base / "Libro.kepub.epub"
            source.write_bytes(b"book contents")
            with patch.object(kobo_device, "_candidate_roots", return_value=[root]), patch.object(kobo_device, "_volume_label", return_value="KOBOeReader"):
                devices = kobo_device.connected_kobos()
                self.assertEqual(len(devices), 1)
                self.assertGreater(devices[0]["free_bytes"], 0)
                first_result = kobo_device.copy_to_kobo(source, devices[0]["id"])
                second_result = kobo_device.copy_to_kobo(source, devices[0]["id"])
                first = Path(first_result["path"])
                second = Path(second_result["path"])
                self.assertEqual(first.read_bytes(), b"book contents")
                self.assertEqual(second.read_bytes(), b"book contents")
                self.assertEqual(first, second)
                self.assertTrue(second_result["already_present"])
                source.write_bytes(b"updated book contents")
                third = Path(kobo_device.copy_to_kobo(source, devices[0]["id"])["path"])
                self.assertEqual(third.name, "Libro (2).kepub.epub")
                self.assertEqual(third.read_bytes(), b"updated book contents")
                library = kobo_device.kobo_library(devices[0]["id"])
                self.assertEqual({book["name"] for book in library["books"]},
                                 {"Libro.kepub.epub", "Libro (2).kepub.epub"})
                self.assertFalse(list(root.glob("*.part")))

    def test_rejects_disconnected_device(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Libro.epub"
            source.write_bytes(b"book")
            with patch.object(kobo_device, "connected_kobos", return_value=[]):
                with self.assertRaisesRegex(ValueError, "No se detecta"):
                    kobo_device.copy_to_kobo(source, "Z:\\")

    def test_api_requires_known_book_and_device(self):
        client = web_app.app.test_client()
        with patch.object(web_app, "connected_kobos", return_value=[]):
            self.assertEqual(client.get("/devices").json, {"devices": []})
        response = client.post("/send-to-kobo", json={"job": "../outside", "filename": "book.epub", "device": "E:\\"})
        self.assertEqual(response.status_code, 400)

    def test_eject_requests_windows_action_and_waits_for_disconnect(self):
        device = {"id": "E:\\", "label": "KOBOeReader", "path": "E:\\"}
        command = SimpleNamespace(returncode=0, stdout="USBSTOR\\DISK&VEN_LINUX\\SERIAL&0\n")
        with patch.object(kobo_device, "connected_kobos", side_effect=[[device], []]), patch.object(kobo_device.subprocess, "run", return_value=command) as run, patch.object(kobo_device, "_request_usb_eject") as eject:
            kobo_device.eject_kobo("E:\\")
            self.assertEqual(run.call_args.kwargs["env"]["MARGEN_KOBO_LETTER"], "E")
            eject.assert_called_once_with("USBSTOR\\DISK&VEN_LINUX\\SERIAL&0")

    def test_native_eject_walks_to_usb_parent(self):
        def locate(pointer, _id, _flags):
            ctypes.cast(pointer, ctypes.POINTER(kobo_device.wintypes.ULONG)).contents.value = 1
            return 0

        def parent(pointer, _node, _flags):
            ctypes.cast(pointer, ctypes.POINTER(kobo_device.wintypes.ULONG)).contents.value = 2
            return 0

        def get_id(node, buffer, _length, _flags):
            buffer.value = "USB\\VID_2237&PID_4237\\KOBO" if node.value == 2 else "USBSTOR\\DISK\\KOBO"
            return 0

        manager = SimpleNamespace(CM_Locate_DevNodeW=Mock(side_effect=locate),
                                  CM_Get_Parent=Mock(side_effect=parent),
                                  CM_Get_Device_IDW=Mock(side_effect=get_id),
                                  CM_Request_Device_EjectW=Mock(return_value=0))
        with patch.object(kobo_device.ctypes, "WinDLL", return_value=manager):
            kobo_device._request_usb_eject("USBSTOR\\DISK\\KOBO")
        manager.CM_Request_Device_EjectW.assert_called_once()

    def test_eject_api_reports_failure(self):
        client = web_app.app.test_client()
        with patch.object(web_app, "eject_kobo", side_effect=RuntimeError("Windows rechazó la expulsión")):
            response = client.post("/eject-kobo", json={"device": "E:\\"})
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
