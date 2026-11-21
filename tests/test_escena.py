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
    '<svg xmlns="http://www.w3.org/2000/svg"'
    ' width="975" height="260" viewBox="0 0 975 260" overflow="hidden">'
)
NS = "http://www.w3.org/2000/svg"
ANIMATED = {"esc-tail", "esc-steam0", "esc-steam1", "esc-steam2", "esc-lids"}

_spec = importlib.util.spec_from_file_location("banner_build", BANNER / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def load(name: str) -> str:
    return (BANNER / name).read_text(encoding="utf-8")


def check_fragments(paths):
    """Chequeo estático de QA.

    Cada fragmento tiene width='975', height='260' y viewBox='0 0 975 260',
    no contiene <text>, sus id son únicos y todo #ref apunta a uno de ellos.
    """
    problems = []
    for path in paths:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if "<text" in text.lower():
            problems.append(f"{path.name}: contiene <text>")
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            problems.append(f"{path.name}: XML inválido: {exc}")
            continue
        if root.tag != f"{{{NS}}}svg":
            problems.append(f"{path.name}: raíz {root.tag}")
        for attr, expected in (
            ("width", "975"),
            ("height", "260"),
            ("viewBox", "0 0 975 260"),
        ):
            got = root.get(attr)
            if got != expected:
                problems.append(f"{path.name}: {attr}={got!r}, se esperaba {expected!r}")
        if root.get("x") is not None or root.get("y") is not None:
            problems.append(f"{path.name}: la raíz no debe llevar x ni y")
        ids = [el.get("id") for el in root.iter() if el.get("id") is not None]
        duplicated = sorted({item for item in ids if ids.count(item) > 1})
        if duplicated:
            problems.append(f"{path.name}: ids duplicados {duplicated}")
        known = set(ids)
        refs = set(re.findall(r"""(?:href|xlink:href)\s*=\s*["']#([^"']+)["']""", text))
        refs.update(re.findall(r"""url\(\s*["']?#([^)"']+)""", text))
        missing = sorted(ref for ref in refs if ref not in known)
        if missing:
            problems.append(f"{path.name}: #ref sin destino {missing}")
    if problems:
        raise AssertionError("\n".join(problems))


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
        names = ("banner-light.svg", "banner-dark.svg")
        legacy = {
            name: (BANNER / name).read_bytes() for name in names if (BANNER / name).is_file()
        }
        with tempfile.TemporaryDirectory() as tmp:
            run_build(Path(tmp))
            written = sorted(path.name for path in Path(tmp).iterdir())
        self.assertEqual(written, sorted(FILES))
        for name in names:
            path = BANNER / name
            if name in legacy:
                self.assertEqual(path.read_bytes(), legacy[name], name)
            else:
                self.assertFalse(path.exists(), name)


class ContractTest(unittest.TestCase):
    def test_root_size_and_reference_placement(self):
        self.assertEqual(build.PLACEMENT, (-513.0462, 22, 1147.5, 306))
        self.assertEqual(build.SLOT, (16, 22, 356, 306, 8))
        self.assertEqual(build.opening_tag(), ROOT_TAG)
        self.assertNotIn(' x="', ROOT_TAG)
        self.assertNotIn(' y="', ROOT_TAG)
        self.assertEqual(build.LOOP, "6s")

    def test_qa_check_fragments(self):
        check_fragments(BANNER / name for name in FILES)

    def test_bytes_shape(self):
        for name in FILES:
            data = (BANNER / name).read_bytes()
            text = data.decode("utf-8")
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), name)
            self.assertNotIn(b"\r", data, name)
            self.assertTrue(data.endswith(b"\n"), name)
            self.assertFalse(text.startswith("<?xml"), name)
            self.assertNotIn("<?xml", text, name)
            self.assertLessEqual(len(data), 70_000, name)
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

    def test_ids_are_unique_and_internal_refs_resolve(self):
        """N3: ids únicos, con prefijo esc-, y todo #ref apunta adentro."""
        xlink_href = "{http://www.w3.org/1999/xlink}href"
        aria_idrefs = {
            "aria-activedescendant",
            "aria-controls",
            "aria-describedby",
            "aria-details",
            "aria-errormessage",
            "aria-flowto",
            "aria-labelledby",
            "aria-owns",
        }
        for name in FILES:
            svg = load(name)
            ids = []
            refs = []
            for el in ET.fromstring(svg).iter():
                for attr, value in el.attrib.items():
                    if attr == "id":
                        ids.append(value)
                    elif attr in ("href", xlink_href):
                        self.assertTrue(value.startswith("#"), f"{name} {attr}={value!r}")
                        refs.append(value[1:])
                    elif attr in aria_idrefs:
                        refs.extend(value.split())
            for match in re.finditer(r"url\(\s*([\"']?)#([^)\"']+)\1\s*\)", svg):
                refs.append(match.group(2))
            duplicated = [item for item in ids if ids.count(item) > 1]
            self.assertEqual(duplicated, [], name)
            self.assertTrue(ids, name)
            for item in ids:
                self.assertTrue(item.startswith("esc-"), item)
            known = set(ids)
            self.assertTrue(refs, name)
            for ref in refs:
                self.assertIn(ref, known, f"{name} #{ref}")

    def test_fragment_is_the_full_scene(self):
        """N8: viewBox del banner entero. build.py no recorta al SLOT."""
        for name in FILES:
            svg = load(name)
            self.assertEqual(svg.splitlines()[0], ROOT_TAG)
            root = ET.fromstring(svg)
            self.assertEqual(root.get("width"), "975")
            self.assertEqual(root.get("height"), "260")
            self.assertEqual(root.get("viewBox"), "0 0 975 260")
            self.assertIsNone(root.get("x"))
            self.assertIsNone(root.get("y"))
            self.assertNotIn("<clipPath", svg)
            self.assertNotIn("clip-path=", svg)
            placed = [float(n) for n in re.findall(r"translate\((-?\d+(?:\.\d+)?)", svg)]
            self.assertGreater(max(placed), 900, name)
            self.assertLess(min(placed), 100, name)

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
