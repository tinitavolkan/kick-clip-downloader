import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import kick_toplu_indir as app


def response(status=200, payload=None):
    return SimpleNamespace(status_code=status, json=lambda: payload)


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def links(self, text):
        path = self.root / "list.txt"
        path.write_text(text, encoding="utf-8-sig")
        return path


    def test_link_formats_and_normalization(self):
        for value in ["https://kick.com/demo/clips/clip_ONE", "http://www.kick.com/demo/?x=1&clip=clip_ONE#share"]:
            with self.subTest(value=value):
                self.assertEqual(app.klip_linki(value), ("https://kick.com/demo/clips/clip_ONE", "clip_ONE"))

    def test_invalid_links_rejected(self):
        for value in ["https://kick.com.evil.test/demo/clips/clip_X", "https://evil.test/demo?clip=clip_X", "file:///demo?clip=clip_X", "https://kick.com/demo", "https://kick.com/demo/clips/clip_X/extra", "https://kick.com/demo?clip=clip_A&clip=clip_B", "https://user@kick.com/demo?clip=clip_X", "https://kick.com/demo?clip=clip_X%2Fbad", "https://["]:
            with self.subTest(value=value):
                self.assertIsNone(app.klip_linki(value))

    def test_comments_duplicates_and_bom(self):
        path = self.links('# comment\n\nhttps://kick.com/demo/clips/clip_ONE\nhttps://kick.com/other?clip=clip_ONE\n"https://kick.com/demo?clip=clip_TWO"\n')
        self.assertEqual([x[1] for x in app.linkleri_oku(path)], ["clip_ONE", "clip_TWO"])


    def test_public_clip_request(self):
        session = MagicMock()
        session.get.return_value = response(payload={"clip": {"clip_url": "https://clips.kick.com/example.mp4"}})
        app.klip_bilgisi_al(session, "https://kick.com/demo/clips/clip_ONE", "clip_ONE")
        self.assertNotIn("Authorization", session.get.call_args.kwargs["headers"])
        self.assertEqual(session.get.call_count, 1)


    def test_denied_access_is_not_retried(self):
        session = MagicMock()
        session.get.return_value = response(403)
        with self.assertRaises(app.ErisimDurdu):
            app.klip_bilgisi_al(session, "https://kick.com/demo/clips/clip_ONE", "clip_ONE")
        self.assertEqual(session.get.call_count, 1)

    def test_final_auth_and_rate_limits_stop(self):
        for status in [401, 403, 429]:
            session = MagicMock()
            session.get.return_value = response(status)
            with self.subTest(status=status), self.assertRaises(app.ErisimDurdu):
                app.klip_bilgisi_al(session, "https://kick.com/demo/clips/clip_ONE", "clip_ONE")
            self.assertEqual(session.get.call_count, 1)

    def test_bad_clip_payloads_rejected(self):
        for payload in [[], {}, {"clip": {}}, {"clip": {"clip_url": "file:///local"}}]:
            session = MagicMock()
            session.get.return_value = response(payload=payload)
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                app.klip_bilgisi_al(session, "https://kick.com/demo/clips/clip_ONE", "clip_ONE")

    def test_download_without_completed_file_fails(self):
        downloader = MagicMock()
        downloader.YoutubeDL.return_value.__enter__.return_value.download.return_value = 0
        (self.root / "clip_ONE.mp4.part").write_bytes(b"partial")
        with patch.object(app, "yt_dlp", downloader), patch.object(app, "INDIRME_KLASORU", self.root), self.assertRaisesRegex(RuntimeError, "arşive"):
            app.medyayi_indir("https://clips.kick.com/example.mp4", "clip_ONE", "https://kick.com/demo")

    def test_completed_download_accepted(self):
        downloader = MagicMock()
        downloader.YoutubeDL.return_value.__enter__.return_value.download.return_value = 0
        (self.root / "clip_ONE.mp4").write_bytes(b"synthetic-video-placeholder")
        with patch.object(app, "yt_dlp", downloader), patch.object(app, "INDIRME_KLASORU", self.root):
            app.medyayi_indir("https://clips.kick.com/example.mp4", "clip_ONE", "https://kick.com/demo")

    def test_dry_run_needs_no_network(self):
        path = self.links("https://kick.com/demo/clips/clip_ONE\n")
        with patch.object(app, "curl_requests", None), patch.object(app, "yt_dlp", None), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.ana_program(["--dry-run", "--links", str(path)]), 0)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["list.txt"])


    def run_batch(self, info=None, download=None):
        path = self.links("https://kick.com/demo/clips/clip_ONE\nhttps://kick.com/demo/clips/clip_TWO\n")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name, value in {"INDIRME_KLASORU": self.root / "videos", "ARSIV_DOSYASI": self.root / "archive.txt", "HATA_DOSYASI": self.root / "errors.txt", "curl_requests": MagicMock()}.items():
            stack.enter_context(patch.object(app, name, value))
        info_mock = stack.enter_context(patch.object(app, "klip_bilgisi_al", side_effect=info, return_value={"clip_url": "https://clips.kick.com/example.mp4"}))
        download_mock = stack.enter_context(patch.object(app, "medyayi_indir", side_effect=download))
        with contextlib.redirect_stdout(io.StringIO()):
            code = app.ana_program(["--links", str(path)])
        return code, info_mock, download_mock

    def test_successes_archived(self):
        code, _, download = self.run_batch()
        self.assertEqual(code, 0)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(app.arsivi_oku(), {"clip_ONE", "clip_TWO"})


    def test_failed_download_not_archived_next_continues(self):
        code, _, download = self.run_batch(download=[RuntimeError("synthetic failure"), None])
        self.assertEqual(code, 1)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(app.arsivi_oku(), {"clip_TWO"})

    def test_auth_failure_stops_queue(self):
        code, info, download = self.run_batch(info=app.ErisimDurdu("HTTP 429"))
        self.assertEqual(code, 1)
        self.assertEqual(info.call_count, 1)
        download.assert_not_called()
        self.assertFalse(app.ARSIV_DOSYASI.exists())

    def test_archived_clip_skipped(self):
        (self.root / "archive.txt").write_text("clip_ONE\n", encoding="utf-8")
        code, info, download = self.run_batch()
        self.assertEqual(code, 0)
        self.assertEqual(info.call_count, 1)
        self.assertEqual(download.call_count, 1)

    def test_keyboard_interrupt_returns_130(self):
        code, _, download = self.run_batch(info=KeyboardInterrupt())
        self.assertEqual(code, 130)
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
