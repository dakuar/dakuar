"""Generate the profile-banner SVGs.

The contours in ``glyphs.json`` were extracted once with fontTools 4.68.0.
fontTools is not imported here. Fonts, both under the SIL Open Font License 1.1:

- IBM Plex Mono Medium (weight 500)
- Noto Sans JP, variable font instanced at weight 600
  (``fontTools.varLib.instancer.instantiateVariableFont(font, {"wght": 600})``)

Outlines were recorded with a y-down pen (``round`` to font units) from those
files. Re-running this script rewrites ``banner-light.svg`` and
``banner-dark.svg`` and does not touch ``glyphs.json``.

Geometry is ported from dakuar/portafolio ``src/features/hero-scene``
(``ruins.ts``, ``scene.ts``, ``cats.ts``). ``actors.ts`` supplies the steam
curve and the tail swing. The tower is redrawn to 21 by 20 cells so it fits
the 32-row banner; the walls keep their x ranges at about 60 percent of their
original height. Stars and the lit window are P1 and are omitted: the three
steam wisps, the tail and the blink already leave no room for 8 to 12 stars
under the limit of 12 animated elements.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CELL = 8
COLS = 121
ROWS = 32
GY = 32  # ground row; the last painted row is GY - 1
TEA_SCALE = 0.017
SCALE = TEA_SCALE * CELL  # 0.136
FONT_PX = round(CELL * 0.9)  # IBM Plex Mono at 0.9 of a cell, as in scene.ts
T_X0, T_X1, T_TOP = 26, 46, -20
BOX = (230, 180, 1070, 765)
CUP_TOP = (301, 630)
TAIL_PIVOT = (948, 700)
RIGHT_EDGE = T_X1 + 5 + 3  # facade overhang plus the portfolio's 3-cell margin

# Tea-cat glyphs, copied from cats.ts. [ch, cx, cy, w, h, role]
TEA_GLYPHS = [
    ["／", 596, 244, 133, 114, "ear"],
    ["l", 688, 245, 12, 100, "ear"],
    ["、", 737, 292, 39, 37, "ear"],
    ["ﾟ", 576, 335, 27, 27, "eye"],
    ["(", 491, 395, 35, 127, "face"],
    ["フ", 864, 403, 68, 104, "face"],
    ["、", 617, 444, 26, 34, "face"],
    ["ﾟ", 731, 448, 29, 29, "eye"],
    ["〃", 717, 493, 57, 30, "face"],
    ["ヽ", 811, 549, 80, 72, "body"],
    ["」", 494, 560, 38, 107, "body"],
    ["旦", 301, 697, 131, 119, "cup"],
    ["(", 446, 697, 34, 127, "paw"],
    [")", 490, 697, 35, 127, "paw"],
    ["ι", 586, 709, 37, 82, "body"],
    ["し", 727, 697, 94, 119, "body"],
    ["(", 801, 697, 35, 127, "body"],
    ["~", 854, 637, 59, 28, "body"],
    [")", 906, 697, 35, 127, "body"],
    ["~", 1004, 696, 119, 35, "tail"],
]

# [x, width, height] in ruin cells. Heights are scaled by 20/62 from ruins.ts.
SKYLINE = (
    (0, 5, 10),
    (-5, 4, 7),
    (49, 5, 14),
    (53, 4, 11),
    (22, 3, 13),
    (4, 3, 11),
)

LIGHT = {
    "bg": "#f6f8fa",
    "stone": "#6b5842",
    "muted": "#7a6f60",
    "cat": "#5b6b7a",
    "eye": "#2f6fa3",
}
DARK = {
    "bg": "#161b22",
    "stone": "#e9d3b6",
    "muted": "#8a8276",
    "cat": "#9aa8b5",
    "eye": "#7fb0d9",
}

TITLE = (
    "Torre de la Catedral de Panamá Viejo en arte ASCII con un gato que toma "
    "café en lo alto. Enlace a dakuar.com"
)

PLEX_ID = {
    "/": "pl-slash",
    "\\": "pl-backslash",
    "|": "pl-bar",
    "_": "pl-under",
    "-": "pl-hyphen",
    "=": "pl-equal",
    "#": "pl-hash",
    "+": "pl-plus",
    ".": "pl-dot",
    ",": "pl-comma",
    '"': "pl-quot",
}


def i32(n: int) -> int:
    n &= 0xFFFFFFFF
    if n >= 0x80000000:
        n -= 0x100000000
    return n


def hash_cell(x: int, y: int) -> float:
    """Same integer hash as ruins.ts. Returns a value in [0, 1)."""
    h = i32(x * 374761393 + y * 668265263)
    h = i32(h ^ ((h & 0xFFFFFFFF) >> 13))
    h = i32(h * 1274126177)
    return ((h & 0xFFFFFFFF) ^ ((h & 0xFFFFFFFF) >> 16)) / 4294967296


def mod(a: int, n: int) -> int:
    return a % n


def _check_hash() -> None:
    expect = {(0, 0): 0.0, (1, -1): 0.79711335292086, (26, -20): 0.2232645247131586}
    for (x, y), wanted in expect.items():
        if abs(hash_cell(x, y) - wanted) > 1e-12:
            raise SystemExit(f"hash mismatch at {x},{y}")


def ragged(x, y, x0, x1, top, depth, seed, flat0=0, flat1=-1) -> bool:
    if x < x0 or x > x1 or flat0 <= x <= flat1:
        return False
    return y < top + math.floor(hash_cell(math.floor(x / 2), seed) * depth)


def arch_hole(x, y, x0, x1, ys, yb) -> bool:
    if x < x0 or x > x1 or y > yb:
        return False
    if y >= ys:
        return True
    cx = (x0 + x1 + 1) / 2
    radius = (x1 - x0 + 1) / 2
    return (x + 0.5 - cx) ** 2 + (y + 0.5 - ys) ** 2 <= radius * radius


def tower_solid(x, y) -> bool:
    shaft = T_X0 <= x <= T_X1 and T_TOP <= y <= -1
    cornice = y in (-18, -11) and T_X0 - 1 <= x <= T_X1 + 1
    base = T_X0 - 3 <= x <= T_X1 + 3 and -8 <= y <= -1
    return shaft or cornice or base


def tower_hole(x, y) -> bool:
    if ragged(x, y, T_X0, T_X1, T_TOP, 2, 7, T_X0 + 1, T_X1 - 1):
        return True
    bells = (
        (T_X0 + 2, T_X0 + 5),
        (T_X0 + 8, T_X0 + 11),
        (T_X0 + 14, T_X0 + 17),
    )
    for x0, x1 in bells:
        if arch_hole(x, y, x0, x1, -15, -12):
            return True
    if arch_hole(x, y, T_X0 + 7, T_X0 + 13, -3, -1):
        return True
    if ragged(x, y, T_X0 - 3, T_X0 - 1, -8, 3, 21):
        return True
    if ragged(x, y, T_X1 + 1, T_X1 + 3, -8, 3, 23):
        return True
    return False


def arch_solid(x, y) -> bool:
    return 7 <= x <= 24 and -10 <= y <= -1


def arch_holes(x, y) -> bool:
    if ragged(x, y, 7, 24, -10, 3, 3):
        return True
    return arch_hole(x, y, 11, 19, -6, -1)


def low_solid(x, y) -> bool:
    return -6 <= x <= 5 and -7 <= y <= -1


def low_holes(x, y) -> bool:
    if ragged(x, y, -6, 5, -7, 2, 11):
        return True
    if arch_hole(x, y, -4, -3, -4, -2):
        return True
    return arch_hole(x, y, 1, 2, -4, -2)


def is_front(x, y) -> bool:
    arch = 12 <= x <= 21 and -2 <= y <= -1 and not ragged(x, y, 12, 21, -2, 2, 31)
    low = -12 <= x <= -8 and -2 <= y <= -1 and not ragged(x, y, -12, -8, -2, 2, 35)
    return arch or low


def is_stone(x, y) -> bool:
    if is_front(x, y):
        return True
    if tower_solid(x, y) and not tower_hole(x, y):
        return True
    if arch_solid(x, y) and not arch_holes(x, y):
        return True
    return low_solid(x, y) and not low_holes(x, y)


def mark(x, y):
    if is_front(x, y):
        return None
    if y in (-18, -11) and T_X0 - 1 <= x <= T_X1 + 1 and is_stone(x, y):
        return "cornice"
    if T_X0 + 9 <= x <= T_X0 + 12 and -10 <= y <= -8 and is_stone(x, y):
        if mod(x - T_X0, 2) == 0 or mod(y, 3) == 0:
            return "bar"
        return "gap"
    if T_TOP < y < -8 and mod(y, 2) == 0 and is_stone(x, y):
        wide = mod(math.floor(y / 2), 2) == 0
        left = x == T_X0 + 1 or (wide and x == T_X0 + 2)
        right = x == T_X1 - 1 or (wide and x == T_X1 - 2)
        if left or right:
            return "quoin"
    return None


def stone_glyph(x, y):
    up = is_stone(x, y - 1)
    down = is_stone(x, y + 1)
    left = is_stone(x - 1, y)
    right = is_stone(x + 1, y)
    if not up and not left:
        return "/", 0.7
    if not up and not right:
        return "\\", 0.7
    if not down and not left:
        return "\\", 0.55
    if not down and not right:
        return "/", 0.55
    if not left or not right:
        return "|", 0.65
    if not up:
        return "_", 0.7
    if not down:
        return "-", 0.55
    wear = hash_cell(x, y)
    if wear < 0.18:
        return None
    if mod(y, 3) == 0:
        return "_", 0.24 + wear * 0.12
    if mod(x + mod(math.floor(y / 3), 2) * 3, 6) == 0:
        return "|", 0.22 + wear * 0.1
    if wear > 0.93:
        return ".", 0.25
    return None


def scene_origin() -> int:
    """Center the ruin span in the 121 columns. The portfolio pins it to the
    right to clear page text; this banner has none."""
    left = -15
    right = RIGHT_EDGE
    span = right - left + 1
    return (COLS - span) // 2 - left


def fmt(n: float) -> str:
    value = round(float(n) + 0.0, 4)
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def load_glyphs():
    data = json.loads((ROOT / "glyphs.json").read_text(encoding="utf-8"))
    return data["plex"], data["noto"]


def plex_transform(info, anchor_x, anchor_y, middle):
    scale = FONT_PX / info_upem(info)
    pen_x = anchor_x - (info["advance"] / 2) * scale
    pen_y = anchor_y - middle * scale
    return pen_x, pen_y, scale


def info_upem(info):
    return info["upem"]


def fit_pen(glyph, cx, cy, width, height, upem):
    ink_w = glyph["xMax"] - glyph["xMin"]
    ink_h = glyph["yMax"] - glyph["yMin"]
    if ink_w <= 0 or ink_h <= 0:
        ink_w = ink_h = upem
    size = (width / ink_w if ink_w > ink_h else height / ink_h) * upem
    scale = size / upem
    center_x = (glyph["xMin"] + glyph["xMax"]) / 2
    center_y = (glyph["yMin"] + glyph["yMax"]) / 2
    return cx - center_x * scale, cy - center_y * scale, scale


def quant(alpha: float) -> float:
    return round(alpha, 2)


class Scene:
    def __init__(self, plex, noto):
        self.plex = plex
        self.noto = noto
        self.ox = scene_origin()
        tea_w = (BOX[2] - BOX[0]) * SCALE
        tea_h = (BOX[3] - BOX[1]) * SCALE
        roof = (self.ox + (T_X0 + T_X1 + 1) / 2) * CELL
        self.tea_x = roof - tea_w / 2
        self.tea_y = (GY + T_TOP) * CELL - tea_h
        self.uses = []  # (font, ch, pen_x, pen_y, scale, fill, alpha, group)
        self.rects = []  # (x, y, w, h, fill, alpha)
        self._build()

    def _cell(self, col, row):
        return col * CELL + CELL / 2, row * CELL + CELL / 2 + 1

    def _on_canvas(self, col, row) -> bool:
        return 0 <= col < COLS and 0 <= row < ROWS

    def _add_plex(self, ch, col, row, fill, alpha):
        if not self._on_canvas(col, row):
            return
        anchor_x, anchor_y = self._cell(col, row)
        glyph = dict(self.plex["glyphs"][ch])
        glyph["upem"] = self.plex["upem"]
        pen_x, pen_y, scale = plex_transform(glyph, anchor_x, anchor_y, self.plex["middle"])
        self.uses.append(("plex", ch, pen_x, pen_y, scale, fill, quant(alpha), ""))

    def _add_noto(self, ch, cx, cy, width, height, fill, alpha, group):
        glyph = self.noto["glyphs"][ch]
        pen_x, pen_y, scale = fit_pen(glyph, cx, cy, width, height, self.noto["upem"])
        self.uses.append(("noto", ch, pen_x, pen_y, scale, fill, quant(alpha), group))

    def _build(self):
        left = -15
        for sx, width, height in SKYLINE:
            for y in range(-height, 0):
                for x in range(sx, sx + width):
                    if is_stone(x, y):
                        continue
                    col, row = self.ox + x, GY + y
                    if x in (sx, sx + width - 1) or y == -height:
                        self._add_plex("_" if y == -height else "|", col, row, "muted", 0.13)
                    elif mod(y, 2) == 0 and mod(x - sx, 2) == 1 and hash_cell(x, y) > 0.3:
                        self._add_plex(".", col, row, "muted", 0.3)

        for y in range(T_TOP - 1, 0):
            for x in range(left, RIGHT_EDGE + 1):
                if not is_stone(x, y):
                    continue
                col, row = self.ox + x, GY + y
                if not self._on_canvas(col, row):
                    continue
                kind = mark(x, y)
                if kind in ("bar", "gap"):
                    self._add_plex("#" if kind == "bar" else "+", col, row, "stone", 0.55 if kind == "bar" else 0.35)
                    continue
                tint = 0.13 if kind == "quoin" else 0.06
                px = col * CELL + 1
                py = row * CELL + 1
                self.rects.append((px, py, CELL - 2, CELL - 2, "stone", quant(tint)))
                if kind == "cornice":
                    glyph = ("=", 0.7)
                else:
                    glyph = stone_glyph(x, y)
                if glyph:
                    self._add_plex(glyph[0], col, row, "stone", glyph[1])

        for col in range(COLS):
            rel = col - self.ox
            roll = hash_cell(rel, 5)
            row = GY - 1
            if roll > 0.55 and not is_stone(rel, -1) and self._on_canvas(col, row):
                self._add_plex('"' if roll > 0.8 else ",", col, row, "muted", 0.5)

        for ch, cx, cy, width, height, role in TEA_GLYPHS:
            gx = self.tea_x + (cx - BOX[0]) * SCALE
            gy = self.tea_y + (cy - BOX[1]) * SCALE
            fill = "eye" if role == "eye" else "cat"
            group = "tail" if role == "tail" else ""
            self._add_noto(ch, gx, gy, width * SCALE, height * SCALE, fill, 1, group)
            if role == "eye":
                self._add_noto("-", gx, gy, width * SCALE, height * SCALE, "eye", 1, "lids")

    def pivot(self):
        return (
            self.tea_x + (TAIL_PIVOT[0] - BOX[0]) * SCALE,
            self.tea_y + (TAIL_PIVOT[1] - BOX[1]) * SCALE,
        )

    def cup(self):
        return (
            self.tea_x + (CUP_TOP[0] - BOX[0]) * SCALE,
            self.tea_y + (CUP_TOP[1] - BOX[1]) * SCALE,
        )

    def steam_local(self):
        glyph = self.noto["glyphs"]["~"]
        return fit_pen(glyph, 0, 0, 80 * SCALE, 28 * SCALE, self.noto["upem"])

    def eye_points(self):
        points = []
        for ch, cx, cy, width, height, role in TEA_GLYPHS:
            if role != "eye":
                continue
            points.append((self.tea_x + (cx - BOX[0]) * SCALE, self.tea_y + (cy - BOX[1]) * SCALE, width * SCALE, height * SCALE))
        return points


def transform(pen_x, pen_y, scale) -> str:
    return f"translate({fmt(pen_x)} {fmt(pen_y)}) scale({fmt(scale)})"


def steam_frames(cup_x, cup_y):
    """One 3 s wisp. Hidden at both ends so the loop meets. Age runs 0..2.6 s."""
    frames = []
    for step in range(0, 27):
        age = step / 10
        fade_in = min(1.0, age / 0.4)
        fade_out = max(0.0, min(1.0, (2.6 - age) / 1.2))
        alpha = 0.7 * fade_in * fade_out
        dx = math.sin(age * 2.4) * 18 * SCALE
        dy = -age * 60 * SCALE
        frames.append((age / 3 * 100, cup_x + dx, cup_y + dy, alpha))
    frames.append((100, frames[0][1], frames[0][2], frames[0][3]))
    return frames


def css(scene: Scene) -> str:
    cup_x, cup_y = scene.cup()
    frames = steam_frames(cup_x, cup_y)
    # Rest pose: one wisp at mid-rise (age 1.3 s), the other two hidden.
    mid_age = 1.3
    mid_x = cup_x + math.sin(mid_age * 2.4) * 18 * SCALE
    mid_y = cup_y - mid_age * 60 * SCALE
    pivot_x, pivot_y = scene.pivot()
    pen_x, pen_y, scale = scene.steam_local()
    body = [
        ".tail,.steam0,.steam1,.steam2{transform-box:view-box}",
        f".tail{{transform-origin:{fmt(pivot_x)}px {fmt(pivot_y)}px;transform:rotate(0rad);animation:tail 3s ease-in-out infinite}}",
        f".steam0{{opacity:.7;transform:translate({fmt(mid_x)}px,{fmt(mid_y)}px);animation:steam 3s linear infinite}}",
        f".steam1,.steam2{{opacity:0;transform:translate({fmt(cup_x)}px,{fmt(cup_y)}px);animation:steam 3s linear infinite}}",
        ".steam1{animation-delay:-1s}.steam2{animation-delay:-2s}",
        ".lids{opacity:0;animation:blink 6s linear infinite}",
        "@keyframes tail{0%,100%{transform:rotate(0rad)}25%{transform:rotate(.22rad)}75%{transform:rotate(-.22rad)}}",
        "@keyframes blink{0%,66.666%{opacity:0}66.75%,69%{opacity:1}69.084%,100%{opacity:0}}",
        "@keyframes steam{",
    ]
    parts = []
    for percent, x, y, alpha in frames:
        label = fmt(percent) if percent not in (0, 100) else str(int(percent))
        if percent == 0:
            label = "0"
        if abs(percent - 100) < 1e-9:
            label = "100"
        parts.append(f"{label}%{{transform:translate({fmt(x)}px,{fmt(y)}px);opacity:{fmt(alpha)}}}")
    body.append("".join(parts))
    body.append("}")
    body.append("@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
    # The rotate lives on the wisp itself so the keyframes only translate.
    scene.steam_transform = f"rotate(90) translate({fmt(pen_x)} {fmt(pen_y)}) scale({fmt(scale)})"
    return "".join(body)


def render(palette, scene: Scene) -> str:
    plex_ids = dict(PLEX_ID)
    noto_ids = {ch: "no-" + format(ord(ch), "x") for ch in scene.noto["glyphs"]}
    defs = []
    for ch, gid in plex_ids.items():
        defs.append(f'<path id="{gid}" d="{scene.plex["glyphs"][ch]["d"]}"/>')
    for ch, gid in noto_ids.items():
        defs.append(f'<path id="{gid}" d="{scene.noto["glyphs"][ch]["d"]}"/>')

    groups = {}
    for font, ch, pen_x, pen_y, scale, fill, alpha, group in scene.uses:
        if font != "plex":
            continue
        gid = plex_ids[ch]
        key = (palette[fill], alpha)
        groups.setdefault(key, []).append(f'<use href="#{gid}" transform="{transform(pen_x, pen_y, scale)}"/>')

    chunks = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="975" height="260" viewBox="0 0 975 260" role="img" aria-labelledby="banner-title">',
        "<!--",
        "IBM Plex Mono (weight 500) and Noto Sans JP (weight 600),",
        "both under the SIL Open Font License 1.1:",
        "https://openfontlicense.org/open-font-license-official-text/",
        "Contours extracted once with fontTools. See banner/build.py.",
        "-->",
        f'<title id="banner-title">{TITLE}</title>',
        f"<style>{css(scene)}</style>",
        "<defs>",
        f'<clipPath id="frame"><rect width="975" height="260" rx="15"/></clipPath>',
        *defs,
        "</defs>",
        '<g clip-path="url(#frame)">',
        f'<rect width="975" height="260" rx="15" fill="{palette["bg"]}"/>',
    ]
    rects = {}
    for x, y, w, h, fill, alpha in scene.rects:
        rects.setdefault((palette[fill], alpha), []).append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>')
    for (color, alpha), items in rects.items():
        chunks.append(f'<g fill="{color}" opacity="{fmt(alpha)}">')
        chunks.extend(items)
        chunks.append("</g>")
    for (color, alpha), uses in groups.items():
        opacity = "" if alpha == 1 else f' opacity="{fmt(alpha)}"'
        chunks.append(f'<g fill="{color}"{opacity}>')
        chunks.extend(uses)
        chunks.append("</g>")

    # Cat glyphs that are not the tail, then the tail group, then the eyelids, then steam.
    def emit_group(name, predicate, extra=""):
        found = [item for item in scene.uses if predicate(item)]
        if not found:
            return
        chunks.append(f'<g class="{name}"{extra}>')
        for font, ch, pen_x, pen_y, scale, fill, alpha, _group in found:
            gid = noto_ids[ch]
            chunks.append(
                f'<use href="#{gid}" fill="{palette[fill]}" transform="{transform(pen_x, pen_y, scale)}"/>'
            )
        chunks.append("</g>")

    emit_group("cat", lambda item: item[0] == "noto" and item[7] == "")
    emit_group("tail", lambda item: item[7] == "tail")
    emit_group("lids", lambda item: item[7] == "lids")

    steam = scene.steam_transform
    for name in ("steam0", "steam1", "steam2"):
        chunks.append(f'<g class="{name}" fill="{palette["muted"]}">')
        chunks.append(f'<use href="#{noto_ids["~"]}" transform="{steam}"/>')
        chunks.append("</g>")

    chunks.append("</g></svg>\n")
    return "\n".join(chunks)


def main() -> None:
    _check_hash()
    plex, noto = load_glyphs()
    # Attach upem onto glyph dicts used by plex_transform via a side channel.
    scene = Scene(plex, noto)
    for name, palette in (("banner-light.svg", LIGHT), ("banner-dark.svg", DARK)):
        text = render(palette, scene)
        (ROOT / name).write_text(text, encoding="utf-8", newline="\n")
    if "--layout" in sys.argv:
        cup = scene.cup()
        pivot = scene.pivot()
        eyes = scene.eye_points()
        sys.stderr.write(
            json.dumps(
                {
                    "ox": scene.ox,
                    "tea": [round(scene.tea_x, 2), round(scene.tea_y, 2)],
                    "cup": [round(cup[0], 2), round(cup[1], 2)],
                    "pivot": [round(pivot[0], 2), round(pivot[1], 2)],
                    "eyes": [[round(p[0], 2), round(p[1], 2)] for p in eyes],
                    "uses": len(scene.uses),
                    "rects": len(scene.rects),
                }
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
