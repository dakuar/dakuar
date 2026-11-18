"""Genera dark_mode.svg y light_mode.svg con profile.json y la API de GitHub.

Uso: python update.py
Lee el token de la variable GH_TOKEN o GITHUB_TOKEN. Solo usa la biblioteca estándar.
"""

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).parent
API = "https://api.github.com/graphql"

# Un intento y tres reintentos. Las esperas son 1 s, 2 s y 4 s.
GRAPHQL_ATTEMPTS = 4
GRAPHQL_REQUESTS = 0

# Medidas en caracteres. STATS_LEFT + 3 + STATS_RIGHT debe ser igual a WIDTH.
# La columna derecha cabe «Commits (12m)» y un número de hasta 6 dígitos.
WIDTH = 58
STATS_LEFT = 31
STATS_RIGHT = 24

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

# El id no puede usarse como argumento en la misma selección, así que va aparte.
USER_ID_QUERY = """
query($login: String!) {
  user(login: $login) {
    id
  }
}
"""

# Una página de repos propios. history.totalCount no pide nodos ni se pagina.
USER_QUERY = """
query($login: String!, $after: String, $author: ID!, $since: GitTimestamp!) {
  user(login: $login) {
    repositories(first: 100, after: $after, ownerAffiliations: OWNER) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        isFork
        defaultBranchRef {
          target {
            ... on Commit {
              history(author: {id: $author}, since: $since) {
                totalCount
              }
            }
          }
        }
      }
    }
  }
}
"""


def graphql(query, variables, token):
    """Ejecuta una query. Ante un 5xx o un fallo de red reintenta 3 veces.

    Las esperas son 1 s, 2 s y 4 s. Un 4xx se propaga sin reintentar.
    """
    global GRAPHQL_REQUESTS
    payload = json.dumps({"query": query, "variables": variables}).encode()
    headers = {"Authorization": f"bearer {token}", "User-Agent": "profile-readme"}
    last_error = None
    for attempt in range(GRAPHQL_ATTEMPTS):
        GRAPHQL_REQUESTS += 1
        request = urllib.request.Request(API, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            error.close()
            if 400 <= error.code < 500:
                raise
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
        else:
            if body.get("errors"):
                sys.exit(f"La API de GitHub devolvió un error: {body['errors'][0]['message']}")
            return body["data"]
        if attempt + 1 < GRAPHQL_ATTEMPTS:
            time.sleep(2**attempt)
    raise last_error


def commit_since(now):
    return (now - dt.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")


def history_count(repo):
    # Un fork no es código propio. Un repo vacío no tiene rama por defecto.
    if not repo or repo.get("isFork"):
        return 0
    ref = repo.get("defaultBranchRef")
    target = ref.get("target") if ref else None
    history = target.get("history") if target else None
    if not history:
        return 0
    return history["totalCount"]


def fetch_stats(login, token, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    since = commit_since(now)
    user = graphql(USER_ID_QUERY, {"login": login}, token)["user"]
    if user is None:
        sys.exit(f"El usuario {login} no existe.")
    # Commits (12m): commits del autor en la rama por defecto de cada repo
    # propio que no es fork, en los últimos 365 días. Los privados entran
    # cuando el token puede leer el repo. Repos sigue contando los forks.
    author = user["id"]
    commits = 0
    repos = None
    after = None
    while True:
        page_user = graphql(
            USER_QUERY,
            {"login": login, "after": after, "author": author, "since": since},
            token,
        )["user"]
        if page_user is None:
            sys.exit(f"El usuario {login} no existe.")
        page = page_user["repositories"]
        repos = page["totalCount"]
        for repo in page["nodes"] or []:
            commits += history_count(repo)
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return {"repos": repos, "commits": commits}


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
    separator = [("text", " | ")]
    return [
        row("Repos", str(stats["repos"]), STATS_LEFT)
        + separator
        + row("Commits (12m)", str(stats["commits"]), STATS_RIGHT, ""),
    ]


def require_email(profile):
    email = profile.get("email")
    if not isinstance(email, str) or not email.strip():
        print("Falta el email en profile.json. No se escribe la ficha.", file=sys.stderr)
        sys.exit(1)
    return email.strip()


def build_lines(profile, stats):
    email = require_email(profile)
    lines = [rule(f"{profile['login']}@github")]
    for section in profile["sections"]:
        if section.get("title"):
            lines += [None, rule(f"- {section['title']}")]
        for entry in section["rows"]:
            if entry is None:
                lines.append([("cc", ".")])
                continue
            lines.append(row(entry[0], entry[1]))
            if entry[0] == "Web":
                lines.append(row("Email", email))
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
    global GRAPHQL_REQUESTS
    GRAPHQL_REQUESTS = 0
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Falta el token. Define la variable GH_TOKEN.")
    profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    # Antes de la API y de escribir: sin email no hay ficha de 13 líneas.
    require_email(profile)
    now = dt.datetime.now(dt.timezone.utc)
    stats = fetch_stats(profile["login"], token)
    lines = build_lines(profile, stats)
    stamp = f"Updated {now:%b} {now.day}, {now.year} {now:%H:%M} UTC"
    for filename, theme in THEMES.items():
        (ROOT / filename).write_text(render(lines, theme, stamp), encoding="utf-8", newline="\n")
    print(json.dumps(stats))
    print(f"graphql requests: {GRAPHQL_REQUESTS}")


if __name__ == "__main__":
    main()
