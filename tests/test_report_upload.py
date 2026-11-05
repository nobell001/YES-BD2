"""匿名上传完整记录 (Leo 2026-11-05 「他要在那次的錯誤報告點匿名上傳」)."""

import base64
import io
import json
import logging
import tempfile
import unittest
from unittest import mock
import urllib.error
import zipfile
from pathlib import Path

from src.tasks import problem_report
from src.ui.shell import problem_image
from src.utils import report_upload
from tests.test_problem_report import Task



def setUpModule():
    # The picture is drawn with Qt fonts: a QApplication must exist.
    from PySide6.QtWidgets import QApplication

    global _APP
    _APP = QApplication.instance() or QApplication([])

class Reply:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        problem_report.set_root(self.folder.name)
        problem_report.install_log_ring()
        log = logging.getLogger("ok")
        task = Task("广场女神像")
        with problem_report.run_scope(task) as scope:
            log.info("广场女神像：开始")
            log.warning("C:" + r"\Users\小明\AppData 没读到 「星光小队」")
            problem_report.note_problem(task, "fail")
            scope.result = False
        [self.record] = problem_report.records()
        self.sent = []
        # These tests are about the station, set up or not.
        station = mock.patch.object(report_upload, "URL", report_upload.STATION_URL)
        station.start()
        self.addCleanup(station.stop)

    def tearDown(self):
        logging.getLogger("ok").removeHandler(problem_report._ring)
        problem_report._ring = None
        problem_report._drop()
        problem_report._last_written.clear()
        problem_report.set_root(None)
        self.folder.cleanup()

    def opener(self, body: bytes):
        def open_(request, timeout):
            self.sent.append(request)
            return Reply(body)

        return open_

    def unpack(self, packed: bytes) -> dict:
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_the_bundle_has_the_record_and_log_without_names_or_paths(self):
        names = [("星光小队", "账号 1")]
        files = self.unpack(report_upload.bundle(self.record, names, picture=lambda r: b"jpg"))
        self.assertEqual("report.json", next(iter(files)))  # the station checks it first
        self.assertIn("log.txt", files)
        self.assertEqual(b"jpg", files["summary.jpg"])
        everything = b"".join(files.values()).decode("utf-8", "replace")
        self.assertNotIn("小明", everything)
        self.assertNotIn("星光小队", everything)
        self.assertIn("账号 1", files["log.txt"].decode("utf-8"))
        report = json.loads(files["report.json"])
        for key in ("path", "log_path", "frame_path", "before_paths"):
            self.assertNotIn(key, report)

    def test_a_big_bundle_drops_the_picture_first(self):
        import os

        big = os.urandom(report_upload.MAX_BYTES + 1000)  # does not compress
        files = self.unpack(report_upload.bundle(self.record, [], picture=lambda r: big))
        self.assertNotIn("summary.jpg", files)
        self.assertIn("log.txt", files)

    def test_the_code_comes_back_and_is_kept_in_the_record(self):
        code, why = report_upload.upload(
            self.record, opener=self.opener(b'{"code":"K7M2QX"}'), version="0.2.32",
            picture=lambda r: None,
        )
        self.assertEqual(("K7M2QX", ""), (code, why))
        [request] = self.sent
        self.assertEqual(report_upload.URL, request.full_url)
        self.assertTrue(request.get_header("User-agent").startswith("YES-BD2/"))
        self.assertTrue(base64.b64decode(request.data).startswith(b"PK\x03\x04"))
        [again] = problem_report.records()
        self.assertEqual("K7M2QX", again["upload_code"])
        self.assertIn("上传代号：K7M2QX", problem_image.summary_text(again))

    def test_the_picture_shows_the_code(self):
        plain = problem_image.render(self.record).height()
        shown = problem_image.render(dict(self.record, upload_code="K7M2QX")).height()
        self.assertGreater(shown, plain)

    def test_no_network_says_so(self):
        def fail(request, timeout):
            raise urllib.error.URLError("down")

        self.assertEqual(
            ("", report_upload.NO_NETWORK),
            report_upload.upload(self.record, opener=fail, picture=lambda r: None),
        )
        self.assertNotIn("upload_code", problem_report.records()[0])

    def test_the_station_says_why(self):
        code, why = report_upload.upload(
            self.record, opener=self.opener('{"error":"上传太频繁"}'.encode()),
            picture=lambda r: None,
        )
        self.assertEqual("", code)
        self.assertIn("上传太频繁", why)

    def test_a_bad_code_is_not_kept(self):
        code, why = report_upload.upload(
            self.record, opener=self.opener(b'{"code":"<script>"}'), picture=lambda r: None
        )
        self.assertEqual(("", report_upload.NO_NETWORK), (code, why))


class UploadButtonTest(unittest.TestCase):
    """复制图片 uploads first, then copies the picture with the code in it."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])

    def actions(self, answer, station=report_upload.STATION_URL):

        from src.ui.shell.problem_page import ReportActions

        calls = []

        class Now:
            def __init__(self, target, name, daemon):
                self.target = target

            def start(self):
                self.target()  # the upload, at once

        def upload(record, picture):
            calls.append(record["path"])
            return answer

        patches = [
            mock.patch.object(report_upload, "URL", station),
            mock.patch("src.ui.shell.problem_page.threading.Thread", Now),
            mock.patch.object(report_upload, "upload", upload),
            mock.patch.object(problem_image, "render", lambda record: self.picture(record)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        actions = ReportActions(200)
        actions.set_record({"label": "x", "finished": 1.0, "path": "a"})
        return actions, calls

    def picture(self, record):
        from PySide6.QtGui import QImage

        image = QImage(10, 10 if not record.get("upload_code") else 20, QImage.Format_RGB32)
        image.fill(0)
        return image

    def test_copy_image_uploads_once_and_the_picture_has_the_code(self):
        from PySide6.QtGui import QGuiApplication

        actions, calls = self.actions(("K7M2QX", ""))
        actions._copy_image()
        self.app.processEvents()
        self.assertEqual(["a"], calls)
        self.assertEqual("K7M2QX", actions._record["upload_code"])
        self.assertEqual(20, QGuiApplication.clipboard().image().height())  # with the code
        actions._copy_text()
        self.app.processEvents()
        self.assertEqual(["a"], calls)  # not again
        self.assertIn("K7M2QX", QGuiApplication.clipboard().text())

    def test_a_failed_upload_still_copies_and_says_why(self):
        from PySide6.QtGui import QGuiApplication

        actions, calls = self.actions(("", report_upload.NO_NETWORK))
        actions._copy_image()
        self.app.processEvents()
        self.assertEqual(10, QGuiApplication.clipboard().image().height())
        self.assertIn("没有代号", actions.note.text())
        self.assertTrue(actions.copy_image.isEnabled())

    def test_without_the_station_the_buttons_work_as_before(self):
        # Leo 2026-11-05 「上傳站下次再做了」: no network, no code, old note.
        from PySide6.QtGui import QGuiApplication

        actions, calls = self.actions(("K7M2QX", ""), station="")
        self.assertIn("Ctrl+V", actions.note.text())
        self.assertNotIn("上传", actions.note.text())
        actions._copy_image()
        actions._copy_text()
        self.app.processEvents()
        self.assertEqual([], calls)
        self.assertNotIn("upload_code", actions._record)
        self.assertNotIn("代号", QGuiApplication.clipboard().text())
        self.assertNotIn("没有代号", actions.note.text())
        self.assertTrue(actions.copy_image.isEnabled())

    def test_the_release_ships_without_the_station(self):
        self.assertEqual("", report_upload.URL)
        self.assertEqual(("", report_upload.NOTHING), report_upload.upload({"label": "x"}))


if __name__ == "__main__":
    unittest.main()
