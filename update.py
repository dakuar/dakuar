"""Genera dark_mode.svg y light_mode.svg con profile.json y la API de GitHub.

Uso: python update.py
Lee el token de la variable GH_TOKEN o GITHUB_TOKEN. Solo usa la biblioteca estándar.
"""

import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).parent
API = "https://api.github.com/graphql"

# Medidas en caracteres. STATS_LEFT + 3 + STATS_RIGHT debe ser igual a WIDTH.
WIDTH = 58
STATS_LEFT = 34
STATS_RIGHT = 21

# Medidas en píxeles. Los valores de ART_* son múltiplos de DOT_PITCH.
CHAR_W = 9.6
LINE_H = 20
TEXT_X = 390
TEXT_Y = 45
SVG_W = 975
ART_X = 20
ART_Y = 25
ART_W = 340
DOT_PITCH = 5

THEMES = {
    "dark_mode.svg": {
        "bg": "#161b22",
        "text": "#c9d1d9",
        "key": "#ffa657",
        "value": "#a5d6ff",
        "cc": "#616e7f",
        "add": "#3fb950",
        "del": "#f85149",
        "art": ["#d21034", "#ffffff", "#005293"],
    },
    "light_mode.svg": {
        "bg": "#f6f8fa",
        "text": "#24292f",
        "key": "#953800",
        "value": "#0a3069",
        "cc": "#a8b3c1",
        "add": "#1a7f37",
        "del": "#cf222e",
        # El blanco de la bandera no se ve sobre el fondo claro. Este tema usa un gris.
        "art": ["#d21034", "#c5ccd6", "#005293"],
    },
}

USER_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    id
    followers { totalCount }
    repositoriesContributedTo(
      first: 100
      includeUserRepositories: false
      contributionTypes: [COMMIT, PULL_REQUEST, PULL_REQUEST_REVIEW, REPOSITORY]
    ) { totalCount nodes { nameWithOwner } }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { nameWithOwner isFork stargazerCount }
    }
  }
}
"""

HISTORY_QUERY = """
query($owner: String!, $name: String!, $id: ID!, $after: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $after, author: {id: $id}) {
            pageInfo { hasNextPage endCursor }
            nodes { additions deletions }
          }
        }
      }
    }
  }
}
"""


def graphql(query, variables, token):
    request = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-readme"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    if body.get("errors"):
        sys.exit(f"La API de GitHub devolvió un error: {body['errors'][0]['message']}")
    return body["data"]


def fetch_stats(login, token):
    owned = []
    after = None
    while True:
        user = graphql(USER_QUERY, {"login": login, "after": after}, token)["user"]
        if user is None:
            sys.exit(f"El usuario {login} no existe.")
        page = user["repositories"]
        owned += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    # Un fork contiene el historial del proyecto original. No lo cuentes como código propio.
    names = [repo["nameWithOwner"] for repo in owned if not repo["isFork"]]
    names += [repo["nameWithOwner"] for repo in user["repositoriesContributedTo"]["nodes"]]

    commits = additions = deletions = 0
    for name in names:
        owner, repo_name = name.split("/")
        after = None
        while True:
            variables = {"owner": owner, "name": repo_name, "id": user["id"], "after": after}
            repo = graphql(HISTORY_QUERY, variables, token)["repository"]
            if repo is None or repo["defaultBranchRef"] is None:
                break
            history = repo["defaultBranchRef"]["target"]["history"]
            commits += len(history["nodes"])
            additions += sum(node["additions"] for node in history["nodes"])
            deletions += sum(node["deletions"] for node in history["nodes"])
            if not history["pageInfo"]["hasNextPage"]:
                break
            after = history["pageInfo"]["endCursor"]

    return {
        "repos": user["repositories"]["totalCount"],
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "stars": sum(repo["stargazerCount"] for repo in owned),
        "followers": user["followers"]["totalCount"],
        "commits": commits,
        "additions": additions,
        "deletions": deletions,
    }


def uptime(since, today):
    years = today.year - since.year
    months = today.month - since.month
    days = today.day - since.day
    if days < 0:
        months -= 1
        last_day_of_previous_month = today.replace(day=1) - dt.timedelta(days=1)
        days += last_day_of_previous_month.day
    if months < 0:
        years -= 1
        months += 12
    parts = [(years, "year"), (months, "month"), (days, "day")]
    shown = [f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in parts if n]
    return ", ".join(shown) or "0 days"


def short(number):
    for limit, suffix in ((1_000_000, "M"), (1_000, "k")):
        if abs(number) >= limit:
            return f"{number / limit:.1f}{suffix}"
    return str(number)


# Una línea es una lista de segmentos (clase CSS, texto). None es una línea vacía.


def row(key, value, width=WIDTH, prefix=". "):
    fixed = len(prefix) + len(key) + 3
    max_value = width - fixed - 2
    if len(value) > max_value:
        value = value[: max_value - 2] + ".."
    dots = "." * (width - fixed - len(value))
    return [("cc", prefix), ("key", key), ("cc", f": {dots} "), ("value", value)]


def rule(title):
    return [("text", f"{title} " + "─" * (WIDTH - len(title) - 1))]


def stats_lines(stats):
    repos = f"{stats['repos']} {{Contributed: {stats['contributed']}}}"
    separator = [("text", " | ")]
    tail = [
        ("value", short(stats["additions"] - stats["deletions"])),
        ("text", " ( "),
        ("add", short(stats["additions"]) + "++"),
        ("text", ", "),
        ("del", short(stats["deletions"]) + "--"),
        ("text", " )"),
    ]
    key = "Lines of Code on GitHub"
    dots = "." * max(1, WIDTH - len(key) - 5 - sum(len(text) for _, text in tail))
    return [
        row("Repos", repos, STATS_LEFT) + separator + row("Stars", str(stats["stars"]), STATS_RIGHT, ""),
        row("Commits", str(stats["commits"]), STATS_LEFT)
        + separator
        + row("Followers", str(stats["followers"]), STATS_RIGHT, ""),
        [("cc", ". "), ("key", key), ("cc", f": {dots} ")] + tail,
    ]


def build_lines(profile, stats, today):
    values = {"uptime": uptime(dt.date.fromisoformat(profile["uptime_since"]), today)}
    lines = [rule(f"{profile['login']}@github")]
    for section in profile["sections"]:
        if section.get("title"):
            lines += [None, rule(f"- {section['title']}")]
        for entry in section["rows"]:
            if entry is None:
                lines.append([("cc", ".")])
            else:
                lines.append(row(entry[0], entry[1].format(**values)))
    return lines + [None, rule("- GitHub Stats")] + stats_lines(stats)


def render(lines, theme, stamp):
    height = TEXT_Y + len(lines) * LINE_H + 25
    art_h = height - 2 * ART_Y
    text_w = round(WIDTH * CHAR_W)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" width="{SVG_W}" height="{height}" '
        f'viewBox="0 0 {SVG_W} {height}" font-family="ui-monospace,SFMono-Regular,Consolas,\'Liberation Mono\',Menlo,monospace" font-size="16">',
        "<style>"
        f"text{{white-space:pre;fill:{theme['text']}}}"
        + "".join(f".{name}{{fill:{theme[name]}}}" for name in ("key", "value", "cc", "add", "del"))
        + "</style>",
        "<defs>",
        '<linearGradient id="fade" x1="0" y1="0" x2="0.35" y2="1">'
        + "".join(
            f'<stop offset="{offset}" stop-color="{color}"/>'
            for offset, color in zip(("0", "0.45", "1"), theme["art"])
        )
        + "</linearGradient>",
        f'<pattern id="dots" width="{DOT_PITCH}" height="{DOT_PITCH}" patternUnits="userSpaceOnUse">'
        f'<circle cx="{DOT_PITCH / 2}" cy="{DOT_PITCH / 2}" r="1.5" fill="#fff"/></pattern>',
        f'<mask id="grid"><rect x="{ART_X}" y="{ART_Y}" width="{ART_W}" height="{art_h}" fill="url(#dots)"/></mask>',
        "</defs>",
        f'<rect width="{SVG_W}" height="{height}" rx="15" fill="{theme["bg"]}"/>',
        f'<rect x="{ART_X}" y="{ART_Y}" width="{ART_W}" height="{art_h}" fill="url(#fade)" mask="url(#grid)"/>',
    ]
    for index, line in enumerate(lines):
        if line is None:
            continue
        # textLength fija el ancho de la línea. Así el borde derecho queda alineado con cualquier fuente.
        full = sum(len(text) for _, text in line) == WIDTH
        fit = f' textLength="{text_w}" lengthAdjust="spacing"' if full else ""
        spans = "".join(f'<tspan class="{cls}">{escape(text)}</tspan>' for cls, text in line)
        out.append(f'<text x="{TEXT_X}" y="{TEXT_Y + index * LINE_H}"{fit}>{spans}</text>')
    out.append(
        f'<text x="{TEXT_X + text_w}" y="{height - 10}" font-size="10" text-anchor="end" class="cc">{escape(stamp)}</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Falta el token. Define la variable GH_TOKEN.")
    profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    stats = fetch_stats(profile["login"], token)
    lines = build_lines(profile, stats, now.date())
    stamp = f"Updated {now:%b} {now.day}, {now.year} {now:%H:%M} UTC"
    for filename, theme in THEMES.items():
        (ROOT / filename).write_text(render(lines, theme, stamp), encoding="utf-8", newline="\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
