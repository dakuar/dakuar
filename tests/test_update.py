"""Reintentos de graphql(), historial de commits y email obligatorio."""

import datetime as dt
import io
import json
import math
import os
import re
import sys
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
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

    def test_query_shape(self):
        src = (ROOT / "update.py").read_text(encoding="utf-8")
        for word in (
            "uptime",
            "stargazerCount",
            "followers",
            "repositoriesContributedTo",
            "contributionsCollection",
            "additions",
            "deletions",
            "privacy: PUBLIC",
        ):
            self.assertNotIn(word, src)
        self.assertIn("ownerAffiliations: OWNER", update.USER_QUERY)
        self.assertIn("history(author: {id: $author}, since: $since)", update.USER_QUERY)
        self.assertIn("totalCount", update.USER_QUERY)
        self.assertNotIn("history(first:", update.USER_QUERY)
        self.assertNotIn("isFork: false", update.USER_QUERY)
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

    def test_second_page_errors_leave_svgs(self):
        pages = [
            Response(user_id()),
            Response(repo_page([repo_node(2)], 2, True)),
            Response({"data": {"user": None}, "errors": [{"message": "repo oculto"}]}),
        ]
        urlopen, sleep, _text = self.run_main(profile_from_disk(), pages)
        self.assertEqual(urlopen.call_count, 3)
        sleep.assert_not_called()


def user_id(value="U_1"):
    return {"data": {"user": {"id": value}}}


def repo_node(count=1, fork=False, empty=False):
    if empty:
        return {"isFork": fork, "defaultBranchRef": None}
    return {
        "isFork": fork,
        "defaultBranchRef": {"target": {"history": {"totalCount": count}}},
    }


def repo_page(nodes, total, has_next, cursor="next"):
    return {
        "data": {
            "user": {
                "repositories": {
                    "totalCount": total,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": nodes,
                }
            }
        }
    }


def request_payload(call):
    return json.loads(call.args[0].data.decode())


class HistoryStatsTest(unittest.TestCase):
    def test_sums_pages_skips_forks_and_empty_repos(self):
        now = dt.datetime(2026, 11, 18, 12, 0, tzinfo=dt.timezone.utc)
        pages = [
            Response(user_id()),
            Response(
                repo_page(
                    [repo_node(3), repo_node(9, fork=True), repo_node(empty=True)],
                    total=4,
                    has_next=True,
                )
            ),
            Response(repo_page([repo_node(5)], total=4, has_next=False)),
        ]
        update.GRAPHQL_REQUESTS = 0
        with mock.patch("update.urllib.request.urlopen", side_effect=pages) as urlopen:
            stats = update.fetch_stats("dakuar", "x", now=now)
        self.assertEqual(stats, {"repos": 4, "commits": 8})
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(update.GRAPHQL_REQUESTS, 3)
        page = request_payload(urlopen.call_args_list[1])
        self.assertEqual(page["variables"]["author"], "U_1")
        self.assertEqual(page["variables"]["since"], "2025-11-18T12:00:00Z")
        self.assertNotIn("author", request_payload(urlopen.call_args_list[0])["variables"])

    def test_request_budget_is_one_page_per_hundred_repos(self):
        total = 150
        first = [repo_node(1) for _ in range(100)]
        second = [repo_node(1) for _ in range(49)] + [repo_node(40, fork=True)]
        pages = [
            Response(user_id()),
            Response(repo_page(first, total, True, "p2")),
            Response(repo_page(second, total, False)),
        ]
        with mock.patch("update.urllib.request.urlopen", side_effect=pages) as urlopen:
            stats = update.fetch_stats("dakuar", "x")
        self.assertEqual(stats["repos"], total)
        self.assertEqual(stats["commits"], 149)
        self.assertEqual(urlopen.call_count, math.ceil(total / 100) + 1)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def render_cards(stats=None, stamp="Updated Nov 18, 2026 00:00 UTC"):
    lines = update.build_lines(profile_from_disk(), stats or STATS)
    return {
        name: update.render(lines, theme, stamp) for name, theme in update.THEMES.items()
    }


def parse_svg(svg):
    return ET.fromstring(svg)


def nested_svg(svg):
    svgs = [el for el in parse_svg(svg).iter() if local(el.tag) == "svg"]
    return svgs[1]


def slot_group(root):
    for el in root.iter():
        if local(el.tag) == "g" and el.get("clip-path") == "url(#slot)":
            return el
    raise AssertionError("falta el grupo del slot")


class SceneFailureTest(unittest.TestCase):
    """A failure leaves both cards byte-identical and exits non-zero."""

    def run_failed(self, side_effect, prepare=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "profile.json").write_text(json.dumps(profile_from_disk()), encoding="utf-8")
        dark = root / "dark_mode.svg"
        light = root / "light_mode.svg"
        before = (b"OLD DARK\n", b"OLD LIGHT\n")
        dark.write_bytes(before[0])
        light.write_bytes(before[1])
        if prepare:
            prepare(root)
        with mock.patch.object(update, "ROOT", root), mock.patch.dict(
            os.environ, {"GH_TOKEN": "x"}
        ), mock.patch("update.time.sleep") as sleep, mock.patch(
            "update.urllib.request.urlopen", side_effect=side_effect
        ) as urlopen, mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(BaseException) as caught:
                update.main()
        err = caught.exception
        if isinstance(err, SystemExit):
            self.assertNotIn(err.code, (0, None))
        self.assertEqual(dark.read_bytes(), before[0])
        self.assertEqual(light.read_bytes(), before[1])
        self.assertEqual(list(root.glob("*.tmp")), [])
        return urlopen, sleep

    def test_429_leaves_svgs_byte_identical(self):
        urlopen, sleep = self.run_failed(http_error(429))
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_5xx_after_retries_leaves_svgs_byte_identical(self):
        errors = [http_error(500), http_error(502), http_error(503), http_error(504)]
        urlopen, sleep = self.run_failed(errors)
        self.assertEqual(urlopen.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])

    def test_missing_fragment_leaves_svgs_byte_identical(self):
        def prepare(root):
            (root / "banner").mkdir()

        urlopen, _sleep = self.run_failed(
            [Response(user_id()), Response(repo_page([repo_node(1)], 1, False))],
            prepare,
        )
        self.assertEqual(urlopen.call_count, 2)

    def test_invalid_xml_leaves_svgs_byte_identical(self):
        real = ROOT / "banner" / "escena-oscuro.svg"

        def prepare(root):
            banner = root / "banner"
            banner.mkdir()
            (banner / "escena-oscuro.svg").write_bytes(real.read_bytes())
            (banner / "escena-claro.svg").write_text("<svg><", encoding="utf-8")

        urlopen, _sleep = self.run_failed(
            [Response(user_id()), Response(repo_page([repo_node(1)], 1, False))],
            prepare,
        )
        self.assertEqual(urlopen.call_count, 2)


class SceneEmbedTest(unittest.TestCase):
    def test_card_size(self):
        for svg in render_cards().values():
            root = parse_svg(svg)
            self.assertEqual(root.get("width"), "975")
            self.assertEqual(root.get("height"), "350")
            self.assertEqual(root.get("viewBox"), "0 0 975 350")

    def test_fragment_is_embedded_under_the_slot_clip(self):
        cards = render_cards()
        for name, theme in update.THEMES.items():
            svg = cards[name]
            raw = (ROOT / theme["scene"]).read_text(encoding="utf-8")
            body = raw[raw.find(">") + 1 :]
            self.assertIn(body, svg)
            self.assertIn('clip-path="url(#slot)"', svg)
            inner = nested_svg(svg)
            self.assertEqual(inner.get("x"), "-513.0462")
            self.assertEqual(inner.get("y"), "22")
            self.assertEqual(inner.get("width"), "1147.5")
            self.assertEqual(inner.get("height"), "306")
            self.assertEqual(inner.get("viewBox"), "0 0 975 260")
            clip = next(el for el in parse_svg(svg).iter() if el.get("id") == "slot")
            rect = next(el for el in clip if local(el.tag) == "rect")
            self.assertEqual(
                (rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height"), rect.get("rx")),
                ("16", "22", "356", "306", "8"),
            )

    def test_opening_tag_rewrite_leaves_the_body(self):
        fragment = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="975" height="260" '
            'viewBox="0 0 975 260" overflow="hidden">'
            '<rect id="esc-keep" width="975" height="260"/></svg>\n'
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        scene = root / "banner" / "escena-claro.svg"
        scene.parent.mkdir(parents=True)
        scene.write_text(fragment, encoding="utf-8")
        theme = update.THEMES["light_mode.svg"]
        lines = update.build_lines(profile_from_disk(), STATS)
        with mock.patch.object(update, "ROOT", root):
            svg = update.render(lines, theme, "Updated Nov 18, 2026 00:00 UTC")
        self.assertIn('<rect id="esc-keep" width="975" height="260"/>', svg)
        self.assertNotIn("<?xml", svg)
        inner = nested_svg(svg)
        self.assertEqual(inner.get("x"), "-513.0462")
        self.assertEqual(inner.get("y"), "22")
        self.assertEqual(inner.get("width"), "1147.5")
        self.assertEqual(inner.get("height"), "306")

    def test_no_dot_gradient_ids(self):
        src = (ROOT / "update.py").read_text(encoding="utf-8")
        self.assertNotIn("esc-", src)
        for token in ("ART_", "DOT_PITCH", 'id="dots"', 'id="fade"', 'id="grid"'):
            self.assertNotIn(token, src)
            for svg in render_cards().values():
                self.assertNotIn(token, svg)

    def test_refs_stay_internal(self):
        for svg in render_cards().values():
            for href in re.findall(r'(?:href|xlink:href)="([^"]*)"', svg):
                self.assertTrue(href.startswith("#"), href)
            for match in re.finditer(r"url\(\s*([^)]*)\s*\)", svg):
                value = match.group(1).strip().strip("\"'")
                self.assertTrue(value.startswith("#"), match.group(0))
            bare = re.sub(r'xmlns="http://www.w3.org/2000/svg"', "", svg)
            bare = re.sub(r"<!--.*?-->", "", bare, flags=re.S)
            self.assertNotIn("http", bare.lower())

    def test_no_active_content(self):
        for svg in render_cards().values():
            lowered = svg.lower()
            for banned in ("<script", "foreignobject", "<iframe", "@import"):
                self.assertNotIn(banned, lowered)

    def test_scene_has_no_text(self):
        lines = update.build_lines(profile_from_disk(), {"repos": 10, "commits": 208})
        for svg in render_cards({"repos": 10, "commits": 208}).values():
            root = parse_svg(svg)
            group = slot_group(root)
            self.assertFalse([el for el in group.iter() if local(el.tag) == "text"])
            inside = {id(el) for el in group.iter()}
            outside = []
            for el in root.iter():
                if local(el.tag) == "text" and id(el) not in inside:
                    outside.append("".join(el.itertext()))
            expected = ["".join(part for _, part in line) for line in lines if line is not None]
            self.assertEqual(outside[:-1], expected)
            self.assertEqual(len(lines), 14)

    def test_ids_are_unique_and_refs_resolve(self):
        xlink = "{http://www.w3.org/1999/xlink}href"
        for svg in render_cards().values():
            ids = []
            refs = []
            for el in parse_svg(svg).iter():
                for attr, value in el.attrib.items():
                    if attr == "id":
                        ids.append(value)
                    elif attr in ("href", xlink):
                        self.assertTrue(value.startswith("#"), value)
                        refs.append(value[1:])
                    elif attr == "aria-labelledby":
                        refs.extend(value.split())
            refs.extend(re.findall(r"url\(\s*[\"']?#([^)\"']+)", svg))
            duplicated = sorted({item for item in ids if ids.count(item) > 1})
            self.assertEqual(duplicated, [])
            known = set(ids)
            self.assertIn("slot", known)
            self.assertIn("card-title", known)
            for ref in refs:
                self.assertIn(ref, known, ref)

    def test_root_exposes_title(self):
        for svg in render_cards().values():
            root = parse_svg(svg)
            self.assertEqual(root.get("role"), "img")
            label = root.get("aria-labelledby")
            self.assertTrue(label)
            titles = [
                el
                for el in root.iter()
                if local(el.tag) == "title" and el.get("id") == label
            ]
            self.assertEqual(len(titles), 1)
            self.assertTrue(titles[0].text and titles[0].text.strip())
            self.assertIn("neofetch", titles[0].text)
            self.assertIn("gato", titles[0].text)

    def test_every_text_line_has_text_length_and_stays_right_of_the_slot(self):
        for svg in render_cards().values():
            root = parse_svg(svg)
            texts = [el for el in root.iter() if local(el.tag) == "text"]
            self.assertTrue(texts)
            for el in texts:
                self.assertIn("textLength", el.attrib)
                self.assertGreaterEqual(float(el.get("x")), 390)
            self.assertIn('textLength="557"', svg)
            self.assertLessEqual(16 + 356, 390)


README_CARD = (
    '<a href="https://dakuar.com"><picture>'
    '<source media="(prefers-color-scheme: dark)" srcset="dark_mode.svg">'
    '<img src="light_mode.svg" alt="Torre de la Catedral de Panamá Viejo en arte ASCII '
    "con un gato que toma café, junto a la ficha de dakuar con formato de neofetch: "
    'enfoque, web, correo, lenguajes, ML y actividad en GitHub. Enlace a dakuar.com">'
    "</picture></a>"
)


class ReadmeTest(unittest.TestCase):
    def test_one_picture_links_home(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(readme.count("<picture>"), 1)
        self.assertEqual(readme.count("</picture>"), 1)
        self.assertIn(README_CARD, readme)
        self.assertLess(readme.find("<a "), readme.find("<picture>"))
        self.assertLess(readme.find("</picture>"), readme.find("</a>"))
        self.assertNotIn("banner/" + "banner-", readme)
        self.assertNotIn("github.com/dakuar", readme)
        self.assertFalse((ROOT / "banner" / "banner-light.svg").exists())
        self.assertFalse((ROOT / "banner" / "banner-dark.svg").exists())


if __name__ == "__main__":
    unittest.main()
