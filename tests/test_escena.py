"""Fragmentos de escena: determinismo, contrato y animación P0."""

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANNER = ROOT / "banner"
FILES = ("escena-claro.svg", "escena-oscuro.svg")
THEMES = {"escena-claro.svg": "claro", "escena-oscuro.svg": "oscuro"}
ROOT_TAG = (
    '<svg xmlns="http://www.w3.org/2000/svg" x="-513.0462" y="22"'
    ' width="1147.5" height="306" viewBox="0 0 975 260" overflow="hidden">'
)
NS = "http://www.w3.org/2000/svg"
ANIMATED = {"esc-tail", "esc-steam0", "esc-steam1", "esc-steam2", "esc-lids"}

_spec = importlib.util.spec_from_file_location("banner_build", BANNER / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def load(name: str) -> str:
    return (BANNER / name).read_text(encoding="utf-8")


def style_of(svg: str) -> str:
    match = re.search(r"<style>(.*)</style>", svg, re.S)
    if not match:
        raise AssertionError("falta <style>")
    return match.group(1)


def css_rules(css: str):
    """Reglas de estilo. Ignora los cuerpos de @keyframes y entra en @media."""
    i = 0
    n = len(css)

    def skip_ws(pos):
        while pos < n and css[pos].isspace():
            pos += 1
        return pos

    def skip_block(start):
        depth = 0
        pos = start
        while pos < n:
            if css[pos] == "{":
                depth += 1
            elif css[pos] == "}":
                depth -= 1
                if depth == 0:
                    return pos + 1
            pos += 1
        raise AssertionError("llaves CSS sin cerrar")

    while i < n:
        i = skip_ws(i)
        if i >= n:
            break
        if css.startswith("@keyframes", i):
            i = skip_block(css.find("{", i))
            continue
        if css.startswith("@media", i):
            i = css.find("{", i) + 1
            continue
        if css[i] == "}":
            i += 1
            continue
        brace = css.find("{", i)
        selector = css[i:brace].strip()
        end = skip_block(brace)
        body = css[brace + 1 : end - 1]
        if selector:
            yield selector, body
        i = end


def animated_classes(css: str) -> set[str]:
    found = set()
    for selector, body in css_rules(css):
        compact = re.sub(r"\s+", "", body)
        if re.search(r"(?<![\w-])animation:none", compact):
            continue
        if not re.search(r"(?<![\w-])animation:", compact):
            continue
        for part in selector.split(","):
            part = part.strip()
            if not part.startswith("."):
                raise AssertionError(f"animación fuera de una clase: {part}")
            found.add(part[1:])
    return found


def run_build(out: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(BANNER / "build.py"), "--out", str(out)],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr.decode() or proc.stdout.decode())


class DeterminismTest(unittest.TestCase):
    def test_two_runs_match_each_other_and_the_versioned_files(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            run_build(Path(first_dir))
            run_build(Path(second_dir))
            for name in FILES:
                first = (Path(first_dir) / name).read_bytes()
                second = (Path(second_dir) / name).read_bytes()
                versioned = (BANNER / name).read_bytes()
                self.assertEqual(first, second, name)
                self.assertEqual(first, versioned, name)
                self.assertEqual(build.render(THEMES[name]), versioned, name)

    def test_render_is_stable_in_process(self):
        for theme in ("claro", "oscuro"):
            self.assertEqual(build.render(theme), build.render(theme))

    def test_out_does_not_rewrite_the_legacy_banners(self):
        legacy = {
            name: (BANNER / name).read_bytes()
            for name in ("banner-light.svg", "banner-dark.svg")
        }
        with tempfile.TemporaryDirectory() as tmp:
            run_build(Path(tmp))
            written = sorted(path.name for path in Path(tmp).iterdir())
        self.assertEqual(written, sorted(FILES))
        for name, data in legacy.items():
            self.assertEqual((BANNER / name).read_bytes(), data, name)


class ContractTest(unittest.TestCase):
    def test_placement_constants_are_the_root(self):
        self.assertEqual(build.PLACEMENT, (-513.0462, 22, 1147.5, 306))
        self.assertEqual(build.SLOT, (16, 22, 356, 306, 8))
        self.assertEqual(build.opening_tag(), ROOT_TAG)
        self.assertEqual(build.LOOP, "6s")

    def test_bytes_shape(self):
        for name in FILES:
            data = (BANNER / name).read_bytes()
            text = data.decode("utf-8")
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), name)
            self.assertNotIn(b"\r", data, name)
            self.assertTrue(data.endswith(b"\n"), name)
            self.assertFalse(text.startswith("<?xml"), name)
            self.assertNotIn("<?xml", text, name)
            self.assertLess(len(data), 80_000, name)
            self.assertEqual(text.splitlines()[0], ROOT_TAG, name)
            ET.fromstring(data)

    def test_themes_differ_only_by_color(self):
        claro = load("escena-claro.svg")
        oscuro = load("escena-oscuro.svg")
        self.assertNotEqual(claro, oscuro)

        def strip(svg):
            return re.sub(r"#[0-9A-Fa-f]{3,8}", "", svg)

        self.assertEqual(strip(claro), strip(oscuro))

    def test_ids_classes_and_keyframes_are_prefixed(self):
        for name in FILES:
            svg = load(name)
            ids = re.findall(r'\bid="([^"]+)"', svg)
            self.assertEqual(len(ids), len(set(ids)), name)
            for item in ids:
                self.assertTrue(item.startswith("esc-"), item)
            for cls in re.findall(r'\bclass="([^"]+)"', svg):
                for token in cls.split():
                    self.assertTrue(token.startswith("esc-"), token)
            css = style_of(svg)
            keyframes = re.findall(r"@keyframes\s+([^{}\s]+)", css)
            self.assertEqual(keyframes, ["esc-tail", "esc-blink", "esc-steam"])
            at_rules = set(re.findall(r"@[A-Za-z-]+", css))
            self.assertEqual(at_rules, {"@keyframes", "@media"})
            for selector, _body in css_rules(css):
                for part in selector.split(","):
                    part = part.strip()
                    self.assertRegex(part, r"^[.#]esc-[A-Za-z0-9_-]+$", part)

    def test_no_external_references_or_text(self):
        for name in FILES:
            svg = load(name)
            lowered = svg.lower()
            for banned in (
                "<script",
                "<iframe",
                "<text",
                "<title",
                "foreignobject",
                "@import",
                "@font-face",
                'role="',
            ):
                self.assertNotIn(banned, lowered, banned)
            hrefs = re.findall(r'\bhref="#([^"]*)"', svg)
            ids = set(re.findall(r'\bid="([^"]+)"', svg))
            self.assertTrue(hrefs, name)
            for href in hrefs:
                self.assertTrue(href.startswith("esc-"), href)
                self.assertIn(href, ids, href)
            for url in re.findall(r"url\(\s*([^)]*)\s*\)", svg):
                self.assertRegex(url.strip("\"'"), r"#esc-[A-Za-z0-9_-]+$")
            bare = svg.replace(f'xmlns="{NS}"', "")
            self.assertNotIn("http", bare.lower(), name)
            for comment in re.findall(r"<!--(.*?)-->", svg, re.S):
                self.assertIsNone(re.search(r"\b20\d{2}\b|\d{4}-\d{2}-\d{2}", comment))

    def test_animation_budget_and_reduced_motion(self):
        for name in FILES:
            svg = load(name)
            css = style_of(svg)
            animated = animated_classes(css)
            self.assertEqual(animated, ANIMATED, name)
            count = 0
            for cls in re.findall(r'\bclass="([^"]+)"', svg):
                if set(cls.split()) & animated:
                    count += 1
            self.assertLessEqual(count, 12, name)
            self.assertEqual(count, len(ANIMATED), name)
            self.assertIn("@media (prefers-reduced-motion: reduce)", css)
            covered = set()
            durations = []
            for selector, body in css_rules(css):
                compact = re.sub(r"\s+", "", body)
                if re.search(r"(?<![\w-])animation:none", compact):
                    covered.update(part.strip()[1:] for part in selector.split(","))
                for match in re.finditer(r"(?<![\w-])animation:([^;}{]+)", body):
                    value = match.group(1)
                    if "none" in value:
                        continue
                    durations.append(value)
                    self.assertIn("6s", value, value)
            self.assertTrue(durations, name)
            self.assertEqual(covered, ANIMATED, name)
            self.assertIn(".esc-lids{opacity:0;", css)
            self.assertIn("@keyframes esc-blink{0%,66.666%{opacity:0}", css)
            self.assertIn(
                "@keyframes esc-tail{0%,50%,100%{transform:rotate(0rad)}", css
            )
            self.assertIn(".esc-tail{", css)
            self.assertIn("transform:rotate(0rad)", css.split("@keyframes", 1)[0])
            self.assertIn(".esc-steam0{opacity:.7;", css)
            self.assertEqual(svg.count("<svg"), 1, name)


if __name__ == "__main__":
    unittest.main()
