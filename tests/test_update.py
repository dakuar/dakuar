"""Reintentos de graphql() y alto de la ficha, con y sin correo."""

import io
import json
import sys
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
        cases = (
            (profile, 14, 350, LINES_WITH_EMAIL),
            (dict(profile, email=None), 13, 330, None),
            (dict(profile, email=""), 13, 330, None),
            (dict(profile, email="   "), 13, 330, None),
        )
        missing = dict(profile)
        missing.pop("email")
        cases = cases + ((missing, 13, 330, None),)
        stamp = "Updated Nov 18, 2026 00:00 UTC"
        for current, count, height, expected in cases:
            lines = update.build_lines(current, STATS)
            self.assertEqual(len(lines), count)
            self.assertEqual(update.TEXT_Y + len(lines) * update.LINE_H + 25, height)
            svg = update.render(lines, update.THEMES["dark_mode.svg"], stamp)
            self.assertIn(f'width="{update.SVG_W}"', svg)
            self.assertIn(f'height="{height}"', svg)
            self.assertIn(f'viewBox="0 0 {update.SVG_W} {height}"', svg)
            self.assertIn('textLength="557"', svg)
            if expected is not None:
                self.assertEqual(joined(lines), expected)
            else:
                self.assertNotIn("Email", svg)

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


if __name__ == "__main__":
    unittest.main()
