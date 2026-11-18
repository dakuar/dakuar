"""Reintentos de graphql(), email obligatorio y alto de la ficha."""

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update

ROOT = Path(__file__).resolve().parents[1]
STATS = {"repos": 2, "commits": 2}

LINES_WITH_EMAIL = [
    "dakuar@github ────────────────────────────────────────────",
    ". Focus: ............................ AI Agent Development",
    ". Web: ........................................ dakuar.com",
    ". Email: ................................... me@dakuar.com",
    ".",
    ". Languages.Programming: ............... Python, C++, Rust",
    ". Languages.Stack: .................. React, Vite, Node.js",
    ". Languages.Real: .............. Spanish, English, Chinese",
    ".",
    ". ML: ....................... PyTorch, pandas, Mamba (SSM)",
    ". Quantum: ........................................ Qiskit",
    "",
    "- GitHub Stats ───────────────────────────────────────────",
    ". Repos: .................... 2 | Commits (12m): ....... 2",
]


def profile_from_disk():
    return json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))


def joined(lines):
    return ["" if line is None else "".join(text for _, text in line) for line in lines]


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self, *_args):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def http_error(code):
    return urllib.error.HTTPError(update.API, code, "error", None, io.BytesIO(b""))


class GraphqlRetryTest(unittest.TestCase):
    def setUp(self):
        update.GRAPHQL_REQUESTS = 0

    def test_retries_three_times_on_5xx(self):
        errors = [http_error(500), http_error(502), http_error(503), http_error(504)]
        with mock.patch("update.time.sleep") as sleep, mock.patch(
            "update.urllib.request.urlopen", side_effect=errors
        ) as urlopen:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                update.graphql("query { x }", {}, "x")
        self.assertEqual(caught.exception.code, 504)
        self.assertEqual(urlopen.call_count, 4)
        self.assertEqual(update.GRAPHQL_REQUESTS, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])

    def test_5xx_then_success_uses_backoff(self):
        ok = Response({"data": {"user": {"id": "1"}}})
        with mock.patch("update.time.sleep") as sleep, mock.patch(
            "update.urllib.request.urlopen", side_effect=[http_error(500), http_error(503), ok]
        ) as urlopen:
            data = update.graphql("query { x }", {}, "x")
        self.assertEqual(data, {"user": {"id": "1"}})
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_network_and_timeout_are_retried(self):
        ok = Response({"data": {"ok": True}})
        with mock.patch("update.time.sleep") as sleep, mock.patch(
            "update.urllib.request.urlopen",
            side_effect=[TimeoutError("timed out"), urllib.error.URLError("reset"), ok],
        ) as urlopen:
            data = update.graphql("query { x }", {}, "x")
        self.assertEqual(data, {"ok": True})
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_4xx_is_not_retried(self):
        for code in (400, 401, 404, 422, 429):
            with self.subTest(code=code):
                update.GRAPHQL_REQUESTS = 0
                with mock.patch("update.time.sleep") as sleep, mock.patch(
                    "update.urllib.request.urlopen", side_effect=http_error(code)
                ) as urlopen:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        update.graphql("query { x }", {}, "x")
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(urlopen.call_count, 1)
                self.assertEqual(update.GRAPHQL_REQUESTS, 1)
                sleep.assert_not_called()


class CardTest(unittest.TestCase):
    def test_height_comes_from_line_count(self):
        profile = profile_from_disk()
        self.assertEqual(profile["email"], "me@dakuar.com")
        lines = update.build_lines(profile, STATS)
        self.assertEqual(len(lines), 14)
        height = update.TEXT_Y + len(lines) * update.LINE_H + 25
        self.assertEqual(height, 350)
        self.assertEqual(joined(lines), LINES_WITH_EMAIL)
        svg = update.render(lines, update.THEMES["dark_mode.svg"], "Updated Nov 18, 2026 00:00 UTC")
        self.assertIn(f'width="{update.SVG_W}"', svg)
        self.assertIn(f'height="{height}"', svg)
        self.assertIn(f'viewBox="0 0 {update.SVG_W} {height}"', svg)
        self.assertIn('textLength="557"', svg)

    def test_commit_number_fits_the_right_column(self):
        lines = update.build_lines(profile_from_disk(), {"repos": 12, "commits": 100000})
        text = joined(lines)[-1]
        values = [part for kind, part in lines[-1] if kind == "value"]
        self.assertEqual(len(text), update.WIDTH)
        self.assertEqual(values, ["12", "100000"])
        self.assertIn("Commits (12m)", text)

    def test_themes_differ_only_by_color(self):
        import re

        lines = update.build_lines(profile_from_disk(), STATS)
        stamp = "Updated Nov 18, 2026 00:00 UTC"
        dark = update.render(lines, update.THEMES["dark_mode.svg"], stamp)
        light = update.render(lines, update.THEMES["light_mode.svg"], stamp)
        stripped = lambda svg: re.sub(r"#[0-9A-Fa-f]{3,8}", "", svg)
        self.assertEqual(stripped(dark), stripped(light))
        self.assertNotEqual(dark, light)

    def test_fetch_stats_is_one_request(self):
        payload = {
            "data": {
                "user": {
                    "repositories": {"totalCount": 7},
                    "contributionsCollection": {"totalCommitContributions": 11},
                }
            }
        }
        update.GRAPHQL_REQUESTS = 0
        with mock.patch("update.urllib.request.urlopen", return_value=Response(payload)) as urlopen:
            stats = update.fetch_stats("dakuar", "x")
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(update.GRAPHQL_REQUESTS, 1)
        self.assertEqual(stats, {"repos": 7, "commits": 11})
        self.assertNotIn("privacy", update.USER_QUERY)
        self.assertIn("ownerAffiliations: OWNER", update.USER_QUERY)
        self.assertIn("totalCommitContributions", update.USER_QUERY)
        self.assertFalse(hasattr(update, "HISTORY_QUERY"))
        self.assertFalse(hasattr(update, "uptime"))


class FailureLeavesSvgTest(unittest.TestCase):
    def run_main(self, profile, side_effect):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        dark = root / "dark_mode.svg"
        light = root / "light_mode.svg"
        dark.write_text("OLD DARK", encoding="utf-8")
        light.write_text("OLD LIGHT", encoding="utf-8")
        stderr = io.StringIO()
        with mock.patch.object(update, "ROOT", root), mock.patch.dict(
            os.environ, {"GH_TOKEN": "x"}
        ), mock.patch("update.time.sleep") as sleep, mock.patch(
            "update.urllib.request.urlopen", side_effect=side_effect
        ) as urlopen, mock.patch("sys.stderr", stderr):
            with self.assertRaises(BaseException) as caught:
                update.main()
        err = caught.exception
        text = stderr.getvalue()
        if isinstance(err, SystemExit):
            code = err.code
            if isinstance(code, str):
                text += code
                code = 1
            elif code is None:
                code = 0
            self.assertNotEqual(code, 0)
        self.assertEqual(dark.read_text(encoding="utf-8"), "OLD DARK")
        self.assertEqual(light.read_text(encoding="utf-8"), "OLD LIGHT")
        return urlopen, sleep, text

    def test_429_is_not_retried_and_svg_stay(self):
        urlopen, sleep, _text = self.run_main(profile_from_disk(), http_error(429))
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_5xx_gives_up_after_three_attempts_and_svg_stay(self):
        errors = [http_error(500), http_error(502), http_error(503), http_error(504)]
        urlopen, sleep, _text = self.run_main(profile_from_disk(), errors)
        self.assertEqual(urlopen.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])

    def test_graphql_errors_exit_without_retry_or_writing(self):
        body = Response({"errors": [{"message": "nope"}]})
        urlopen, sleep, _text = self.run_main(profile_from_disk(), [body])
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_missing_email_exits_without_writing_svg(self):
        cases = {
            "ausente": lambda profile: profile.pop("email", None),
            "vacio": lambda profile: profile.__setitem__("email", ""),
            "null": lambda profile: profile.__setitem__("email", None),
            "blanco": lambda profile: profile.__setitem__("email", "   "),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                profile = profile_from_disk()
                mutate(profile)
                with self.assertRaises(SystemExit) as caught:
                    update.build_lines(profile, STATS)
                self.assertNotEqual(caught.exception.code, 0)
                urlopen, _sleep, text = self.run_main(profile, http_error(500))
                urlopen.assert_not_called()
                self.assertIn("email", text.lower())


if __name__ == "__main__":
    unittest.main()
