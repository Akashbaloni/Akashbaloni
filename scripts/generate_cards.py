#!/usr/bin/env python3
"""
Generates self-hosted SVG cards for the GitHub profile README:

  profile/overview.svg   -> public repos, total stars, followers, all-time contributions
  profile/streak.svg     -> total contributions, current streak, longest streak
  profile/activity.svg   -> contribution graph for the last 30 days

Uses only the Python standard library and the GitHub GraphQL API, so it
runs inside GitHub Actions with the default GITHUB_TOKEN. No third-party
servers are involved, so the cards can't break when a public service is down.

If anything fails, existing SVGs are left untouched (the README keeps
showing yesterday's numbers instead of a broken image).

Usage:
  GITHUB_TOKEN=... python scripts/generate_cards.py --user Akashbaloni
  python scripts/generate_cards.py --user Akashbaloni --demo   # offline preview
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"

# Tokyo Night palette (matches the github-readme-stats "tokyonight" theme)
BG = "#1a1b27"
TEXT = "#c0caf5"
MUTED = "#787c99"
GRID = "#2a2e45"
BLUE = "#7aa2f7"
PURPLE = "#bb9af7"
GREEN = "#9ece6a"
AMBER = "#e0af68"
CYAN = "#7dcfff"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif"


# --------------------------------------------------------------------------- data
def gql(token: str, query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-readme-cards",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch(user: str, token: str) -> dict:
    profile_q = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        followers { totalCount }
        repositories(ownerAffiliations: OWNER, privacy: PUBLIC, first: 100, after: $cursor) {
          totalCount
          nodes { stargazerCount }
          pageInfo { hasNextPage endCursor }
        }
        contributionsCollection { contributionYears }
      }
    }"""
    stars, cursor = 0, None
    while True:
        u = gql(token, profile_q, {"login": user, "cursor": cursor})["user"]
        repos = u["repositories"]
        stars += sum(n["stargazerCount"] for n in repos["nodes"])
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]

    cal_q = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    days: dict[str, int] = {}
    total = 0
    for year in u["contributionsCollection"]["contributionYears"]:
        cal = gql(
            token,
            cal_q,
            {"login": user, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
        )["user"]["contributionsCollection"]["contributionCalendar"]
        total += cal["totalContributions"]
        for week in cal["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]

    return {
        "repos": repos["totalCount"],
        "stars": stars,
        "followers": u["followers"]["totalCount"],
        "total": total,
        "days": days,
    }


def demo_data() -> dict:
    rng = random.Random(7)
    today = dt.date.today()
    days = {}
    for i in range(400):
        d = today - dt.timedelta(days=i)
        days[d.isoformat()] = 0 if rng.random() < 0.3 else rng.randint(1, 12)
    for i in range(9):  # guarantee a visible current streak
        days[(today - dt.timedelta(days=i)).isoformat()] = rng.randint(1, 9)
    return {"repos": 24, "stars": 57, "followers": 41, "total": sum(days.values()), "days": days}


# ------------------------------------------------------------------------ streaks
def streaks(days: dict[str, int], today: dt.date):
    series = sorted((dt.date.fromisoformat(k), v) for k, v in days.items())
    series = [(d, v) for d, v in series if d <= today]

    longest = (0, None, None)
    run, start = 0, None
    for d, v in series:
        if v > 0:
            if run == 0:
                start = d
            run += 1
            if run > longest[0]:
                longest = (run, start, d)
        else:
            run = 0

    lookup = dict(series)
    cur_end = today if lookup.get(today, 0) > 0 else today - dt.timedelta(days=1)
    cur, d = 0, cur_end
    while lookup.get(d, 0) > 0:
        cur += 1
        d -= dt.timedelta(days=1)
    current = (cur, d + dt.timedelta(days=1) if cur else None, cur_end if cur else None)
    first = next((d for d, v in series if v > 0), None)
    return current, longest, first


def fmt_date(d: dt.date | None) -> str:
    return d.strftime("%b %-d, %Y") if d else ""


def fmt_range(a, b) -> str:
    if not a:
        return "No streak yet"
    if a == b:
        return fmt_date(a)
    if a.year == b.year:
        return f"{a.strftime('%b %-d')} – {b.strftime('%b %-d, %Y')}"
    return f"{fmt_date(a)} – {fmt_date(b)}"


def short(n: int) -> str:
    if n >= 10_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n:,}"


# ---------------------------------------------------------------------------- svg
def card(width: int, height: int, body: str, title: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
<title>{escape(title)}</title>
<style>
  .t {{ font-family: {FONT}; fill: {TEXT}; }}
  .m {{ font-family: {FONT}; fill: {MUTED}; }}
</style>
<rect x="0.5" y="0.5" rx="10" width="{width - 1}" height="{height - 1}" fill="{BG}"/>
{body}
</svg>
"""


ICONS = {  # 16x16 octicon-style paths
    "repo": "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z",
    "star": "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z",
    "people": "M2 5.5a3.5 3.5 0 1 1 5.898 2.549 5.508 5.508 0 0 1 3.034 4.084.75.75 0 1 1-1.482.235 4 4 0 0 0-7.9 0 .75.75 0 0 1-1.482-.236A5.507 5.507 0 0 1 3.102 8.05 3.493 3.493 0 0 1 2 5.5ZM11 4a3.001 3.001 0 0 1 2.22 5.018 5.01 5.01 0 0 1 2.56 3.012.749.749 0 0 1-.885.954.752.752 0 0 1-.549-.514 3.507 3.507 0 0 0-2.522-2.372.75.75 0 0 1-.574-.73v-.352a.75.75 0 0 1 .416-.672A1.5 1.5 0 0 0 11 5.5.75.75 0 0 1 11 4Zm-5.5-.5a2 2 0 1 0-.001 3.999A2 2 0 0 0 5.5 3.5Z",
    "commit": "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
}


def overview_svg(data: dict) -> str:
    w, h = 850, 110
    tiles = [
        ("repo", "Public Repos", short(data["repos"]), BLUE),
        ("star", "Total Stars", short(data["stars"]), AMBER),
        ("people", "Followers", short(data["followers"]), PURPLE),
        ("commit", "Contributions", short(data["total"]), GREEN),
    ]
    tw = (w - 40) / 4
    body = []
    for i, (icon, label, value, color) in enumerate(tiles):
        x = 20 + i * tw
        body.append(
            f'<g transform="translate({x:.1f},0)">'
            f'<rect x="6" y="18" width="{tw - 12:.1f}" height="74" rx="8" fill="{color}" fill-opacity="0.08" stroke="{color}" stroke-opacity="0.35"/>'
            f'<g transform="translate(22,32) scale(1.1)"><path d="{ICONS[icon]}" fill="{color}"/></g>'
            f'<text x="46" y="45" class="m" font-size="13">{label}</text>'
            f'<text x="22" y="79" class="t" font-size="26" font-weight="700" fill="{color}" style="fill:{color}">{value}</text>'
            f"</g>"
        )
    return card(w, h, "\n".join(body), "GitHub overview")


def streak_svg(data: dict, today: dt.date) -> str:
    (cur, cs, ce), (lng, ls, le), first = streaks(data["days"], today)
    w, h = 850, 190
    col = w / 3

    def block(i, value, label, sub, color, ring=False):
        cx = col * i + col / 2
        parts = [f'<g>']
        if ring:
            parts.append(
                f'<circle cx="{cx:.1f}" cy="72" r="42" fill="none" stroke="{color}" stroke-width="5" stroke-opacity="0.9"/>'
                f'<text x="{cx:.1f}" y="83" text-anchor="middle" class="t" font-size="30" font-weight="700" style="fill:{color}">{value}</text>'
                f'<text x="{cx:.1f}" y="140" text-anchor="middle" class="t" font-size="15" font-weight="600" style="fill:{color}">{label}</text>'
            )
            # small flame on top of the ring
            parts.append(
                f'<g transform="translate({cx - 9:.1f},18)"><rect x="-4" y="-2" width="26" height="26" rx="13" fill="{BG}"/>'
                f'<path d="M9 0c1 5-4 7-4 12a5.5 5.5 0 0 0 11 0c0-3-2-5-2-5 0 2-1 3-2 3 0-4-1-7-3-10z" fill="{color}"/></g>'
            )
        else:
            parts.append(
                f'<text x="{cx:.1f}" y="83" text-anchor="middle" class="t" font-size="30" font-weight="700">{value}</text>'
                f'<text x="{cx:.1f}" y="140" text-anchor="middle" class="t" font-size="15" font-weight="600">{label}</text>'
            )
        parts.append(f'<text x="{cx:.1f}" y="162" text-anchor="middle" class="m" font-size="12">{escape(sub)}</text></g>')
        return "".join(parts)

    since = f"{fmt_date(first)} – Present" if first else "No contributions yet"
    body = "\n".join(
        [
            f'<line x1="{col:.1f}" y1="35" x2="{col:.1f}" y2="160" stroke="{GRID}"/>',
            f'<line x1="{2 * col:.1f}" y1="35" x2="{2 * col:.1f}" y2="160" stroke="{GRID}"/>',
            block(0, short(data["total"]), "Total Contributions", since, TEXT),
            block(1, cur, "Current Streak", fmt_range(cs, ce), AMBER, ring=True),
            block(2, lng, "Longest Streak", fmt_range(ls, le), TEXT),
        ]
    )
    return card(w, h, body, "GitHub contribution streak")


def activity_svg(data: dict, today: dt.date, n_days: int = 30) -> str:
    w, h = 850, 300
    left, right, top, bottom = 55, 25, 55, 50
    pw, ph = w - left - right, h - top - bottom
    dates = [today - dt.timedelta(days=n_days - 1 - i) for i in range(n_days)]
    vals = [data["days"].get(d.isoformat(), 0) for d in dates]
    vmax = max(vals) or 1
    step = max(1, -(-vmax // 4))  # ceil(vmax/4)
    ymax = step * 4

    def X(i):
        return left + pw * i / (n_days - 1)

    def Y(v):
        return top + ph - ph * v / ymax

    grid = []
    for k in range(5):
        v = step * k
        y = Y(v)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{GRID}" stroke-dasharray="{"0" if k == 0 else "3 4"}"/>')
        grid.append(f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" class="m" font-size="11">{v}</text>')
    for i, d in enumerate(dates):
        if i % 3 == 0 or i == n_days - 1:
            grid.append(f'<text x="{X(i):.1f}" y="{h - bottom + 20}" text-anchor="middle" class="m" font-size="11">{d.day}</text>')

    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
    area = f"M{X(0):.1f},{Y(0):.1f} L" + " L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals)) + f" L{X(n_days - 1):.1f},{Y(0):.1f} Z"
    dots = "".join(
        f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3.2" fill="{BG}" stroke="{CYAN}" stroke-width="2"><title>{d.strftime("%b %-d")}: {v} contribution{"s" if v != 1 else ""}</title></circle>'
        for i, (d, v) in enumerate(zip(dates, vals))
    )
    period = f"{dates[0].strftime('%b %-d')} – {dates[-1].strftime('%b %-d, %Y')}"
    total = sum(vals)
    body = f"""
<defs>
  <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{BLUE}" stop-opacity="0.45"/>
    <stop offset="1" stop-color="{BLUE}" stop-opacity="0.02"/>
  </linearGradient>
</defs>
<text x="25" y="33" class="t" font-size="18" font-weight="600" style="fill:{BLUE}">Contribution Graph · last {n_days} days</text>
<text x="{w - 25}" y="33" text-anchor="end" class="m" font-size="12">{period} · {total} contributions</text>
{''.join(grid)}
<g>
  <path d="{area}" fill="url(#ag)"/>
  <polyline points="{pts}" fill="none" stroke="{BLUE}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
  {dots}
</g>
<text x="{left + pw / 2:.1f}" y="{h - 8}" text-anchor="middle" class="m" font-size="11">Day of month</text>
"""
    return card(w, h, body, "Contribution graph for the last 30 days")


# --------------------------------------------------------------------------- main
def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    print(f"wrote {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER"))
    ap.add_argument("--out", default="profile")
    ap.add_argument("--demo", action="store_true", help="render with fake data (offline preview)")
    args = ap.parse_args()

    if not args.user:
        print("No user given (--user)", file=sys.stderr)
        return 1

    try:
        if args.demo:
            data = demo_data()
        else:
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise RuntimeError("GITHUB_TOKEN is not set")
            data = fetch(args.user, token)
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()  # IST
        outputs = {
            "overview.svg": overview_svg(data),
            "streak.svg": streak_svg(data, today),
            "activity.svg": activity_svg(data, today),
        }
    except Exception as exc:  # keep yesterday's cards instead of breaking the README
        print(f"::warning::Card generation failed, keeping existing SVGs: {exc}")
        return 0

    out = Path(args.out)
    for name, svg in outputs.items():
        write_atomic(out / name, svg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
