import contextlib
import io
import os
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
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def links(self, text):
        path = self.root / "list.txt"
        path.write_text(text, encoding="utf-8-sig")
        return path

    def config(self, example=False):
        path = self.root / "config.js"
        values = ("YOUR_CLIENT_ID", "YOUR_CLIENT_SECRET") if example else ("test-id", "test-secret")
        path.write_text(f'KICK_CLIENT_ID: "{values[0]}", KICK_CLIENT_SECRET: "{values[1]}"', encoding="utf-8")
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

    def test_placeholder_config_rejected(self):
        with self.assertRaisesRegex(ValueError, "Örnek"):
            app.js_config_oku(self.config(True))

    def test_config_is_read_not_executed(self):
        self.assertEqual(app.js_config_oku(self.config()), ("test-id", "test-secret"))

    def test_environment_precedes_file(self):
        with patch.dict(os.environ, {"KICK_CLIENT_ID": "env-id", "KICK_CLIENT_SECRET": "env-secret"}):
            self.assertEqual(app.kimlik_bilgileri(self.root / "absent"), ("env-id", "env-secret"))

    def test_incomplete_environment_rejected(self):
        with patch.dict(os.environ, {"KICK_CLIENT_ID": "test-id"}):
            with self.assertRaisesRegex(ValueError, "birlikte"):
                app.kimlik_bilgileri()

    def test_token_request_contract(self):
        client = MagicMock()
        client.post.return_value = response(payload={"access_token": "dummy-token"})
        with patch.object(app, "curl_requests", client):
            self.assertEqual(app.app_token_al("test-id", "test-secret"), "dummy-token")
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], "https://id.kick.com/oauth/token")
        self.assertEqual(kwargs["data"]["grant_type"], "client_credentials")
        self.assertEqual(kwargs["data"]["client_secret"], "test-secret")
        self.assertNotIn("redirect_uri", kwargs["data"])

    def test_token_error_does_not_echo_response(self):
        client = MagicMock()
        client.post.return_value = response(401)
        client.post.return_value.text = "sensitive-response"
        with patch.object(app, "curl_requests", client), self.assertRaises(RuntimeError) as error:
            app.app_token_al("test-id", "test-secret")
        self.assertNotIn("sensitive-response", str(error.exception))
        self.assertNotIn("test-secret", str(error.exception))

    def test_malformed_token_responses_rejected(self):
        for payload in [[], {}, {"access_token": ""}]:
            client = MagicMock()
            client.post.return_value = response(payload=payload)
            with self.subTest(payload=payload), patch.object(app, "curl_requests", client), self.assertRaises(RuntimeError):
                app.app_token_al("test-id", "test-secret")

    def test_public_clip_request_has_no_token(self):
        session = MagicMock()
        session.get.return_value = response(payload={"clip": {"clip_url": "https://clips.kick.com/example.mp4"}})
        app.klip_bilgisi_al(session, "https://kick.com/demo/clips/clip_ONE", "clip_ONE", "dummy-token")
        self.assertNotIn("Authorization", session.get.call_args.kwargs["headers"])
        self.assertEqual(session.get.call_count, 1)

    def test_single_authenticated_fallback(self):
        session = MagicMock()
        session.get.side_effect = [response(401), response(payload={"clip": {"clip_url": "https://clips.kick.com/example.mp4"}})]
        app.klip_bilgisi_al(session, "https://kick.com/demo/clips/clip_ONE", "clip_ONE", "dummy-token")
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args.kwargs["headers"]["Authorization"], "Bearer dummy-token")

    def test_no_empty_token_retry(self):
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
                app.klip_bilgisi_al(session, "https://kick.com/demo/clips/clip_ONE", "clip_ONE", "dummy-token")
            self.assertEqual(session.get.call_count, 1 if status == 429 else 2)

    def test_bad_clip_payloads_rejected(self):
        for payload in [[], {}, {"clip": {}}, {"clip": {"clip_url": "file:///local"}}]:
            session = MagicMock()
            session.get.return_value = response(payload=payload)
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                app.klip_bilgisi_al(session, "https://kick.com/demo/clips/clip_ONE", "clip_ONE", "dummy-token")

    def test_download_without_completed_file_fails(self):
        downloader = MagicMock()
        downloader.YoutubeDL.return_value.__enter__.return_value.download.return_value = 0
        (self.root / "clip_ONE.mp4.part").write_bytes(b"partial")
        with patch.object(app, "yt_dlp", downloader), patch.object(app, "INDIRME_KLASORU", self.root), self.assertRaisesRegex(RuntimeError, "arşive"):
            app.medyayi_indir("https://clips.kick.com/example.mp4", "title", "clip_ONE", "https://kick.com/demo")

    def test_completed_download_accepted(self):
        downloader = MagicMock()
        downloader.YoutubeDL.return_value.__enter__.return_value.download.return_value = 0
        (self.root / "clip_ONE.mp4").write_bytes(b"synthetic-video-placeholder")
        with patch.object(app, "yt_dlp", downloader), patch.object(app, "INDIRME_KLASORU", self.root):
            app.medyayi_indir("https://clips.kick.com/example.mp4", "title", "clip_ONE", "https://kick.com/demo")

    def test_dry_run_requires_no_credentials_or_network(self):
        path = self.links("https://kick.com/demo/clips/clip_ONE\n")
        with patch.object(app, "curl_requests", None), patch.object(app, "yt_dlp", None), patch.object(app, "kimlik_bilgileri") as credentials, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.ana_program(["--dry-run", "--links", str(path)]), 0)
        credentials.assert_not_called()
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["list.txt"])

    def test_check_api_prints_no_token_and_needs_no_list(self):
        output = io.StringIO()
        with patch.object(app, "curl_requests", MagicMock()), patch.object(app, "kimlik_bilgileri", return_value=("test-id", "test-secret")), patch.object(app, "app_token_al", return_value="dummy-token"), contextlib.redirect_stdout(output):
            self.assertEqual(app.ana_program(["--check-api"]), 0)
        self.assertNotIn("dummy-token", output.getvalue())
        self.assertNotIn("test-secret", output.getvalue())

    def run_batch(self, info=None, download=None):
        path = self.links("https://kick.com/demo/clips/clip_ONE\nhttps://kick.com/demo/clips/clip_TWO\n")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name, value in {"INDIRME_KLASORU": self.root / "videos", "ARSIV_DOSYASI": self.root / "archive.txt", "HATA_DOSYASI": self.root / "errors.txt", "curl_requests": MagicMock()}.items():
            stack.enter_context(patch.object(app, name, value))
        stack.enter_context(patch.object(app, "kimlik_bilgileri", return_value=("test-id", "test-secret")))
        stack.enter_context(patch.object(app, "app_token_al", return_value="dummy-token"))
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

    def test_batch_without_config_never_requests_oauth(self):
        with patch.object(app, "CONFIG_ADAYLARI", []):
            code, info, _ = self.run_batch()
        self.assertEqual(code, 0)
        self.assertEqual(info.call_args.args[3], "")

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
