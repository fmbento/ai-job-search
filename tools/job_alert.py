#!/usr/bin/env python3
"""Daily Priority-1 job alert for this fork. Reports only - it NEVER edits
files, pushes, or applies to anything.

Each run reads two sources with the same Priority-1 keyword file
(tools/job_alert_keywords.txt, from .claude/skills/job-scraper/search-queries.md):

- Real Work From Anywhere category pages (the same seven pages and parsing
  anchors as the realworkfromanywhere-search CLI)
- the MoAIJobs RSS feed (the complete board in one request, the same feed
  and "Role at Company" title convention as the moaijobs-search CLI)

and comments the NEW matches on one rolling GitHub issue titled
"Job alert - Priority 1 matches". A failing source is skipped with a note in
the comment; the run only fails when NO source yields any postings at all -
a silent green run on a markup change is the one failure mode this alert
must not have.

State lives in the issue's own comment history (the already-reported URLs),
so there is no cache to refresh and nothing to push: the workflow runs with
the built-in GITHUB_TOKEN, the only mutation is appending comments to this
fork's own issue, and the alert reaches the user as a normal GitHub
notification. Same report/act boundary and posture as upstream-watch.yml.

Each match also carries a location tag: "EU/UK ok" or "US-only", derived
from the posting's own location text (the MoAIJobs RSS "Location:" field);
Real Work From Anywhere postings are worldwide-remote by board policy and
always tag EU/UK ok. Keyword lines in tools/job_alert_keywords.txt may
carry an optional "| us-only" or "| anywhere" suffix to pin the label for
postings matching that keyword. Tags are triage hints, never filters -
nothing is excluded from the alert.

Every daily comment also embeds a small machine-readable payload (a JSON
array inside an HTML comment, invisible when rendered) with that run's
scanned/fresh/backlog counts per board-category. A second cron, Sunday
07:20 UTC, collects the payloads from the past 7 days and posts a weekly
trend summary - new matches per board, per category, and per day - as one
more comment on the same issue. Same state-in-comments design.

Matching is case-insensitive with word boundaries over title + company +
skill tags. "New" cards count as 0 days old; a posting whose age cannot be
parsed is treated as fresh rather than silently dropped (the seen-set, not
the date, prevents re-alerts). Categories that fail to fetch are skipped;
the run only fails when NO postings could be parsed at all - a silent green
run on a markup change is the one failure mode this alert must not have.

stdlib only (urllib, email.utils, subprocess only for `git credential fill`),
Python 3.12.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import email.utils
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://www.realworkfromanywhere.com"
MOAI_BASE_URL = "https://www.moaijobs.com"
MOAI_RSS_PATH = "/ai-jobs.rss"

# Same seven category pages the realworkfromanywhere-search CLI scrapes.
CATEGORY_PATHS = {
    "fullstack": "/remote-fullstack-jobs",
    "backend": "/remote-backend-jobs",
    "software-developer": "/remote-software-developer-jobs",
    "product": "/remote-product-jobs",
    "design": "/remote-design-jobs",
    "sales-and-marketing": "/remote-sales-and-marketing-jobs",
    "customer-support": "/remote-customer-support-jobs",
}

ISSUE_TITLE = "Job alert - Priority 1 matches"
UA = "Mozilla/5.0 (compatible; realworkfromanywhere-cli/1.0)"

# Included in a new issue's first (bootstrap) comment, so the setup is
# self-documenting months from now.
HOW_TO_READ = (
    "<details><summary>\U0001F4D6 How to read this issue</summary>\n\n"
    "- Each comment is one morning's sweep of "
    "[Real Work From Anywhere](https://www.realworkfromanywhere.com) + "
    "[MoAIJobs](https://www.moaijobs.com) against the Priority-1 keywords in "
    "`tools/job_alert_keywords.txt` (edit that file to retune).\n"
    "- The top list is what's **new** inside the 3-day window. A posting is "
    "never alerted twice - this comment history is the memory.\n"
    "- The collapsed block is older matches, listed once for context.\n"
    "- Sundays add a **Weekly trend** comment (built from hidden counters "
    "inside each daily comment).\n"
    "- **No comment on a day = nothing new.** You get notified because the "
    "repo is on Watch (All Activity): email + GitHub mobile app. A red run "
    "under Actions means a portal broke - that's the alarm, not noise.\n"
    "- Each match carries a location tag: 🌍 EU/UK ok (worldwide remote or "
    "outside the US) or 🇺🇸 US-only (not workable from the profile's EU/UK "
    "base without sponsorship). Tags are hints, not filters.\n"
    "\n</details>")

ROOT = Path(__file__).resolve().parent.parent
KEYWORDS_FILE = ROOT / "tools" / "job_alert_keywords.txt"


# --------------------------------------------------------------------------
# Keyword loading / matching
# --------------------------------------------------------------------------

def load_keywords(path: Path = KEYWORDS_FILE) -> list[str]:
    """One term per line; blank lines and #-comments ignored."""
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line.lower())
    if not terms:
        raise SystemExit(f"no keywords found in {path}")
    return terms


GEO_US_ONLY = "us-only"
GEO_ANYWHERE = "anywhere"  # override value meaning "not US-only"


def parse_keyword_line(line: str) -> tuple[str, str | None]:
    """Split an optional geo suffix off a keyword line: "llm" -> ("llm", None),
    "digital humanities | anywhere" -> ("digital humanities", "anywhere").
    An unrecognized suffix keeps the whole line as the term, exactly as
    untagged keyword files always behaved."""
    stripped = line.strip().lower()
    term, sep, geo = stripped.partition("|")
    geo = geo.strip() if sep else ""
    if sep and geo in (GEO_US_ONLY, GEO_ANYWHERE):
        return term.strip(), geo
    return stripped, None


def load_keyword_entries(
        path: Path = KEYWORDS_FILE) -> list[tuple[str, str | None]]:
    """(term, geo_override) pairs - load_keywords() plus optional geo tags."""
    entries: list[tuple[str, str | None]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(parse_keyword_line(line))
    if not entries:
        raise SystemExit(f"no keywords found in {path}")
    return entries


def keyword_pattern(terms: list[str]) -> re.Pattern[str]:
    # \b around each term so "llm" matches "LLM Engineer" but "ai" does not
    # match inside "email"/"maintain". re.escape keeps multi-word terms
    # ("applied ai") intact.
    return re.compile(
        r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b",
        re.IGNORECASE,
    )


# --------------------------------------------------------------------------
# Portal fetch + card parsing (anchors identical to the CLI's helpers.ts)
# --------------------------------------------------------------------------

def fetch(url: str, retries: int = 4, timeout: int = 20) -> str:
    delay = 1.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return ""
            last = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
    raise RuntimeError(f"fetch failed after {retries + 1} attempts: {url}: {last}")


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def parse_cards(html: str, category: str) -> list[dict]:
    """RWFA card anchors per url-reference.md: split on the card anchor, then
    pull title (h3), company (truncate p), relative date, salary, and tags."""
    cards: list[dict] = []
    for chunk in html.split('<a href="/jobs/')[1:]:
        head = re.match(r'([a-z0-9-]+)" class="block w-full rounded-lg', chunk)
        if not head:
            continue
        slug = head.group(1)
        idm = re.search(r"-(\d+)$", slug)
        title = re.search(r"<h3[^>]*>([\s\S]*?)</h3>", chunk, re.IGNORECASE)
        if not idm or not title:
            continue
        company = re.search(
            r'<p class="text-base truncate font-medium[^"]*">([\s\S]*?)</p>',
            chunk, re.IGNORECASE)
        date = re.search(
            r'class="hidden md:block[^"]*text-base-content/80"*>([\s\S]*?)</span>',
            chunk, re.IGNORECASE)
        salary = re.search(
            r'<span class="whitespace-nowrap">(\$[\s\S]*?)</span>', chunk,
            re.IGNORECASE)
        tags = [_clean(m) for m in re.findall(
            r'<span class="badge[^"]*">([\s\S]*?)</span>', chunk, re.IGNORECASE)]
        cards.append({
            "id": idm.group(1),
            "title": _clean(title.group(1)),
            "company": _clean(company.group(1)) if company else None,
            "date": _clean(date.group(1)) if date else None,
            "salary": _clean(salary.group(1)) if salary else None,
            "tags": [t for t in tags if t],
            # RWFA is fully-remote worldwide by board policy -> EU/UK ok.
            "location": None,
            "geo": geo_from_location(None, category),
            "url": f"{BASE_URL}/jobs/{slug}",
            "category": category,
        })
    return cards


def relative_date_to_days(text: str | None) -> int | None:
    """Same contract as the CLI's helper: unparseable -> None."""
    if not text:
        return None
    t = text.strip().lower()
    if t == "new":
        return 0
    m = re.match(r"^(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago$", t)
    if not m:
        return None
    n = int(m.group(1))
    return {"second": 0, "minute": 0, "hour": 0, "day": n, "week": n * 7,
            "month": n * 30}.get(m.group(2))


# --------------------------------------------------------------------------
# Location tagging: a coarse triage hint, not a gate. The profile's
# deal-breaker is relocation outside the EU/UK without sponsorship, so
# "US-only" matches are the ones not worth clicking from Europe.
# --------------------------------------------------------------------------

GEO_OK = "ok"  # EU/UK-accessible: worldwide remote, or located outside the US

GEO_LABELS = {
    GEO_OK: "🌍 EU/UK ok",
    GEO_US_ONLY: "🇺🇸 US-only",
}

US_LOCATION_RE = re.compile(
    r"\b(usa|u\.s\.a|u\.s|united states|us[- ]only"
    r"|remote[-\s/()\u2013\u2014]*(?:us|usa|u\.s)"
    r"|(?:us|usa|u\.s)[-\s/()\u2013\u2014]*remote"
    r"|san francisco|new york|nyc|boston|austin|seattle|denver|chicago"
    r"|atlanta|miami|dallas|houston|los angeles|mountain view|palo alto"
    r"|san jose|portland|philadelphia|phoenix|washington dc|ann arbor)\b",
    re.IGNORECASE)


def geo_from_location(location: str | None, category: str) -> str | None:
    """ok (EU/UK-accessible) / us-only / None (unknown). Real Work From
    Anywhere postings are fully-remote worldwide by board policy; MoAIJobs
    ones are judged from the RSS "Location:" text, untagged when absent."""
    if category != "moaijobs":
        return GEO_OK
    if not location:
        return None
    return GEO_US_ONLY if US_LOCATION_RE.search(location) else GEO_OK


def fetch_all_cards() -> tuple[list[dict], list[str]]:
    """Fetch every category page; skip individual failures. Returns
    (cards, failed_category_names) - the caller decides what total failure
    means. Dedupe by id, first category wins."""
    seen: set[str] = set()
    cards: list[dict] = []
    failed: list[str] = []
    for name, path in CATEGORY_PATHS.items():
        try:
            page_cards = parse_cards(fetch(f"{BASE_URL}{path}"), name)
        except Exception as exc:  # noqa: BLE001 - one bad page must not kill the run
            failed.append(f"{name}: {exc}")
            continue
        for card in page_cards:
            if card["id"] not in seen:
                seen.add(card["id"])
                cards.append(card)
    return cards, failed


def _relative_age_text(published: str | None) -> str | None:
    """Convert an RSS pubDate into the same relative-date text the RWFA cards
    carry ("New", "3 days ago"), so classify()/relative_date_to_days() work
    unchanged and the comment shows a familiar age. Absolute ages also let
    MoAI postings age out of the window like RWFA ones - without this, an
    RSS-only source would stay "fresh" forever and re-list every past match
    in each daily comment. Returns None when unparseable, which classify()
    conservatively treats as fresh (the seen-set prevents re-alerts)."""
    if not published:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(published.strip())
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    age_days = (datetime.datetime.now(datetime.timezone.utc) - dt).days
    if age_days < 0:
        age_days = 0
    return "New" if age_days < 1 else f"{age_days} day{'' if age_days == 1 else 's'} ago"


def _moai_location(item: str) -> str | None:
    r"""The "Location:" value from an RSS item's description. The feed mixes
    raw HTML and double-escaped HTML inside CDATA, so normalize both to plain
    text first. Labels like "Location Policy:" must not match (the colon has
    to follow "Location" directly). None when the field is absent."""
    raw = re.search(r"<description>([\s\S]*?)</description>", item)
    if not raw:
        return None
    text = _cdata(raw.group(1))
    text = (text.replace("&lt;", "<").replace("&gt;", ">")
                .replace("&amp;nbsp;", " ").replace("&nbsp;", " ")
                .replace("&amp;", "&"))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    m = re.search(
        r"Location\s*:\s*(.{0,120}?)(?=\s*(?:Salary\s*:|Skills\s*:|Company\s*:"
        r"|Apply|About|Job [Dd]escription|Requirements)|$)",
        text)
    if not m:
        return None
    value = m.group(1).strip(" \t-,;")
    return value or None


def parse_moai_rss(xml: str) -> list[dict]:
    """MoAIJobs RSS items, same feed and anchors as the moaijobs-search CLI
    (url-reference.md). Titles read "Role at Company" - the company is split
    off the LAST " at " so roles containing " at " survive. Description
    bodies are not kept: the alert only needs title/company/salary/tags and
    the posting URL. An item without a parsable /job/<slug>-<id> link is
    skipped without breaking its siblings."""
    cards: list[dict] = []
    for item in xml.split("<item>")[1:]:
        title_raw = re.search(r"<title>([\s\S]*?)</title>", item)
        link_raw = re.search(r"<link>([\s\S]*?)</link>", item)
        if not title_raw or not link_raw:
            continue
        title_all = _clean(_cdata(title_raw.group(1)))
        url = _cdata(link_raw.group(1)).strip()
        m = re.search(r"/job/([a-z0-9-]+)-(\d+)/?$", url)
        if not title_all or not m:
            continue
        slug, job_id = m.group(1), m.group(2)
        at = title_all.rfind(" at ")
        title, company = title_all, None
        if 0 < at < len(title_all) - 4:
            title, company = title_all[:at], title_all[at + 4:] or None
        pub_raw = re.search(r"<pubDate>([\s\S]*?)</pubDate>", item)
        pub_text = _cdata(pub_raw.group(1)).strip() if pub_raw else None
        salary = re.search(r"<strong>Salary:</strong>\s*([\s\S]*?)</p>", item,
                           re.IGNORECASE)
        tags = [_clean(t) for t in re.findall(
            r"<strong>Skills?:</strong>\s*([\s\S]*?)</p>", item, re.IGNORECASE)]
        location = _moai_location(item)
        cards.append({
            "id": job_id,
            "title": title,
            "company": company,
            # Relative age synthesized from the absolute pubDate (see
            # _relative_age_text); None when unparseable -> fresh.
            "date": _relative_age_text(pub_text),
            "salary": _clean(salary.group(1)) if salary else None,
            "tags": [t for t in ", ".join(tags).split(",") if t.strip()],
            "location": location,
            "geo": geo_from_location(location, "moaijobs"),
            "url": f"{MOAI_BASE_URL}/job/{slug}-{job_id}",
            "category": "moaijobs",
        })
    return cards


def _cdata(inner: str) -> str:
    m = re.search(r"<!\[CDATA\[([\s\S]*?)\]\]>", inner)
    return m.group(1) if m else inner


def collect_postings() -> tuple[list[dict], list[str]]:
    """Both sources, deduped by URL (first source wins). Returns
    (postings, failure_notes) - the caller decides what total failure means.
    One failing source degrades to the other with a visible note; only a
    completely empty sweep is fatal."""
    postings: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set()

    rwfa_cards, failed_categories = fetch_all_cards()
    for card in rwfa_cards:
        if card["url"] not in seen:
            seen.add(card["url"])
            postings.append(card)
    for name in failed_categories:
        notes.append(f"realworkfromanywhere: category fetch failed, skipped: {name}")
    if not rwfa_cards:
        notes.append("realworkfromanywhere: zero postings parsed - portal "
                     "unreachable or markup changed (see "
                     ".agents/skills/realworkfromanywhere-search/url-reference.md)")

    try:
        moai_cards = parse_moai_rss(fetch(f"{MOAI_BASE_URL}{MOAI_RSS_PATH}"))
    except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
        moai_cards = []
        notes.append(f"moaijobs: RSS fetch failed, skipped: {exc}")
    for card in moai_cards:
        if card["url"] not in seen:
            seen.add(card["url"])
            postings.append(card)
    if not moai_cards:
        notes.append("moaijobs: zero postings parsed from RSS - feed "
                     "unreachable or markup changed (see "
                     ".agents/skills/moaijobs-search/url-reference.md)")

    return postings, notes


# --------------------------------------------------------------------------
# Weekly counts (payload embedded in each daily comment; the Sunday cron
# aggregates the past 7 days of payloads into one trend comment)
# --------------------------------------------------------------------------

WEEKLY_MARK = "<!-- weekly-counts "


def build_weekly_payload(checked: str, postings: list[dict],
                         fresh: list[dict], backlog: list[dict]
                         ) -> tuple[str, int]:
    """(payload, version) for this daily run: per (board, category) scanned /
    fresh / backlog counts plus a day tag. JSON inside an HTML comment is
    invisible when GitHub renders the comment, yet survives verbatim in
    fetch_comments() - so the Sunday summary needs no extra state, no cache
    file, and no pushes.

    Version 2 (current) buckets also carry the fresh posting URLs, so the
    Sunday aggregation can dedupe a match that stays fresh across up to
    max_age_days consecutive daily runs (or matches in two categories).
    Version 1 payloads (no "fresh_urls") are still aggregated, per bucket,
    with cross-run dedupe impossible for them.
    """
    fresh_urls = {c["url"] for c in fresh}
    backlog_urls = {c["url"] for c in backlog}
    by_key: dict[tuple[str, str], dict] = {}
    for card in postings:
        day = card.get("day") or "-"
        entry = by_key.setdefault((card["category"], day),
                                  {"scanned": 0, "fresh": 0, "backlog": 0,
                                   "fresh_urls": []})
        entry["scanned"] += 1
        if card["url"] in fresh_urls:
            entry["fresh"] += 1
            entry["fresh_urls"].append(card["url"])
        elif card["url"] in backlog_urls:
            entry["backlog"] += 1
    buckets = [
        {"board": cat, "day": day, "scanned": e["scanned"], "fresh": e["fresh"],
         "backlog": e["backlog"], "fresh_urls": e["fresh_urls"]}
        for (cat, day), e in sorted(by_key.items())
    ]
    raw = json.dumps({"v": 2, "checked": checked, "buckets": buckets},
                     ensure_ascii=True, sort_keys=True)
    token = base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii")
    return f"{WEEKLY_MARK}{token}-->", 2


def extract_weekly_payloads(comments: list[dict]) -> list[dict]:
    """All weekly payloads oldest-first, plus their comment date. Comments
    without a payload are skipped silently (the rolling issue predates the
    weekly feature) and so are payloads that fail to decode - one bad or
    hand-edited comment must not break the Sunday summary."""
    out: list[dict] = []
    for c in comments:
        m = re.search(re.escape(WEEKLY_MARK) + r"([A-Za-z0-9_-]+={0,2})-->",
                      c["body"])
        if not m:
            continue
        try:
            raw = base64.urlsafe_b64decode(m.group(1).encode("ascii"))
            data = json.loads(raw)
        except (ValueError, json.JSONDecodeError) as exc:  # ValueError covers binascii
            print(f"note: unparseable weekly payload in comment "
                  f"{c.get('id', '?')} - skipped ({exc})", file=sys.stderr)
            continue
        out.append({
            "created": c.get("created", ""),
            "v": int(data.get("v", 1)),
            "checked": data.get("checked", ""),
            "buckets": data.get("buckets", []),
        })
    return out


def _bucket_day(entry: dict, created: str) -> str:
    """Day tag of a bucket: the embedded "day", else the comment's creation
    date (they are the same run). "unknown" when neither is usable - such
    buckets fall outside any 7-day window and are dropped."""
    day = entry.get("day") or "-"
    if day != "-":
        return day
    return (created or "")[:10] or "unknown"


def _board_name(label: str) -> str:
    """Category labels double as board names: "moaijobs" is its own board;
    every RWFA category page folds into the realworkfromanywhere board."""
    return "moaijobs" if label == "moaijobs" else "realworkfromanywhere"


def _board_label(board: str) -> str:
    return "MoAIJobs" if board == "moaijobs" else "Real Work From Anywhere"


def _tally(dimension: dict, key: str, entry: dict) -> None:
    """Fold one bucket into one dimension of the weekly aggregate. scanned /
    backlog are summed over runs; fresh counts are deduped by URL when the
    payload carries fresh_urls (v2) and added as-is otherwise (v1)."""
    slot = dimension.setdefault(key, {"scanned": 0, "backlog": 0, "fresh": 0,
                                      "urls": set()})
    slot["scanned"] += entry.get("scanned", 0)
    slot["backlog"] += entry.get("backlog", 0)
    urls = entry.get("fresh_urls")
    if urls is None:
        slot["fresh"] += entry.get("fresh", 0)  # v1 payload: no dedupe possible
    else:
        before = len(slot["urls"])
        slot["urls"].update(urls)
        slot["fresh"] += len(slot["urls"]) - before


def aggregate_week(payloads: list[dict], today: datetime.date) -> dict:
    """Fold the past 7 days (today-6 .. today, UTC) of daily payloads into
    per-category / per-day / per-board totals. Buckets whose day is outside
    the window or unparsable are skipped; a URL that stayed fresh across
    several daily runs counts once."""
    start = today - datetime.timedelta(days=6)
    per_category: dict = {}
    per_day: dict = {}
    per_board: dict = {}
    for p in payloads:
        for entry in p.get("buckets", []):
            day_text = _bucket_day(entry, p.get("created", ""))
            try:
                day = datetime.date.fromisoformat(day_text)
            except ValueError:
                continue
            if not (start <= day <= today):
                continue
            label = entry.get("board") or "?"
            _tally(per_category, label, entry)
            _tally(per_day, day_text, entry)
            _tally(per_board, _board_name(label), entry)
    return {
        "start": start.isoformat(),
        "end": today.isoformat(),
        "runs": len(payloads),
        "per_category": per_category,
        "per_day": per_day,
        "per_board": per_board,
        "days_with_data": len(per_day),
        "total_fresh": sum(v["fresh"] for v in per_board.values()),
        "total_backlog": sum(v["backlog"] for v in per_category.values()),
    }


def render_weekly_comment(payloads: list[dict], today: datetime.date,
                          run_url: str) -> str:
    """The Sunday trend comment: new Priority-1 matches per board, per
    category, and a small per-day bar chart over the past 7 days."""
    agg = aggregate_week(payloads, today)
    parts = [f"## Weekly trend — {agg['start']} to {agg['end']}", ""]
    if not payloads:
        parts += ["No weekly counts found in the issue's comments yet — the "
                  "daily alert only started embedding them recently. The "
                  "first complete summary lands next Sunday.", ""]
    elif not agg["per_category"]:
        parts += [f"No Priority-1 matches in this week's {agg['runs']} daily "
                  "sweep(s).", ""]
    else:
        parts += [f"**{agg['total_fresh']} new Priority-1 match(es)** this "
                  f"week, from {agg['runs']} daily sweep(s), "
                  f"{agg['days_with_data']} day(s) with matches:", ""]
        board_bits = [f"{_board_label(b)}: **{v['fresh']}**"
                      for b, v in sorted(agg["per_board"].items(),
                                         key=lambda kv: (-kv[1]["fresh"],
                                                         kv[0]))]
        parts += [f"- **By board:** " + " · ".join(board_bits)]
        cat_bits = [f"{name}: {v['fresh']}"
                    for name, v in sorted(agg["per_category"].items(),
                                          key=lambda kv: (-kv[1]["fresh"],
                                                          kv[0]))]
        parts += [f"- **By category:** " + " · ".join(cat_bits)]
        parts += ["", "**Per day:**", ""]
        max_fresh = max((v["fresh"] for v in agg["per_day"].values()),
                        default=0)
        for day_text in sorted(agg["per_day"]):
            v = agg["per_day"][day_text]
            bar = ("█" * max(1, round(v["fresh"] * 10 / max_fresh))
                   if max_fresh else "·")
            weekday = datetime.date.fromisoformat(day_text).strftime("%a")
            parts.append(f"- `{day_text}` ({weekday}): {bar} {v['fresh']}")
        parts += ["", f"*Older-than-window backlog seen during the week's "
                      f"sweeps: {agg['total_backlog']} (already reported "
                      "once; not counted above).*", ""]
    parts += [
        "",
        "---",
        f"*Counts come from hidden per-run counters embedded in the daily "
        f"comments on this issue. Keywords: `tools/job_alert_keywords.txt` "
        f"· boards: [Real Work From Anywhere]({BASE_URL}) · "
        f"[MoAIJobs]({MOAI_BASE_URL}) · [run]({run_url}) · "
        "stop it: disable the `Job alert` workflow.*",
    ]
    return "\n".join(parts) + "\n"


def weekly_summary(comments: list[dict], today: datetime.date,
                   run_url: str) -> str:
    """One-call entry point for the Sunday cron: comments in, weekly trend
    comment out."""
    return render_weekly_comment(extract_weekly_payloads(comments), today,
                                 run_url)


# --------------------------------------------------------------------------
# Alert selection
# --------------------------------------------------------------------------

def classify(cards: list[dict], pattern: re.Pattern[str], max_age_days: int
             ) -> tuple[list[dict], list[dict]]:
    """Split matches into (fresh within the window, matched-but-older backlog).
    An unparseable date counts as fresh: the seen-set prevents re-alerts, so
    alerting is the conservative choice when the date is unreadable."""
    fresh: list[dict] = []
    backlog: list[dict] = []
    for card in cards:
        haystack = " ".join([card["title"], card["company"] or "", *card["tags"]])
        if not pattern.search(haystack):
            continue
        age = relative_date_to_days(card["date"])
        if age is None or age <= max_age_days:
            fresh.append(card)
        else:
            backlog.append(card)
    return fresh, backlog


def split_new(fresh: list[dict], already_seen: set[str]
              ) -> tuple[list[dict], list[dict]]:
    """fresh -> (not yet reported, reported before and still in the window)."""
    new = [c for c in fresh if c["url"] not in already_seen]
    still_open = [c for c in fresh if c["url"] in already_seen]
    return new, still_open


# --------------------------------------------------------------------------
# GitHub REST (stdlib urllib - no gh dependency). Auth: GH_TOKEN wins (the
# workflow sets it to the built-in GITHUB_TOKEN); otherwise the token is read
# from git's own credential store via `git credential fill`, so local runs
# authenticate exactly like a local `git push` - no extra setup, no secrets
# in the repo. GH_REPO (owner/name) comes from the workflow environment;
# locally it is derived from the origin remote.
# --------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"


def _repo_slug() -> str:
    """owner/name for API paths: GH_REPO first, else parsed from the origin
    remote URL (ssh and https shapes)."""
    repo = os.environ.get("GH_REPO", "").strip().strip("/")
    if repo:
        return repo
    url = subprocess.run(["git", "remote", "get-url", "origin"],
                         capture_output=True, text=True, check=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise SystemExit(f"cannot derive a GitHub repo from origin: {url}")
    return m.group(1)


def _github_token() -> str:
    """GH_TOKEN first (CI); else git's credential store (local runs). An
    empty result is allowed: reads on a public repo work unauthenticated,
    and a write then fails with the API's clear 401 instead of a guess."""
    token = os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    try:
        probe = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, check=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"note: git credential fill failed ({exc}) - continuing "
              "unauthenticated", file=sys.stderr)
        return ""
    for line in probe.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def _gh_request(method: str, path: str, body: dict | None = None
                ) -> tuple[int, object]:
    """One REST call; returns (status, decoded JSON). 404 is a normal
    outcome (no issue yet) and is returned, not raised; any other HTTP
    error raises after urllib's own handling."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "job-alert-script",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{GITHUB_API}/repos/{_repo_slug()}/{path.lstrip('/')}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, None
        raise


def find_issue(force_number: int | None) -> int | None:
    """The rolling issue's number, or None when it does not exist yet."""
    if force_number is not None:
        return force_number
    status, issues = _gh_request(
        "GET", "issues?state=open&per_page=100&sort=created&direction=desc")
    if status >= 400:
        raise RuntimeError(f"GitHub issue search failed with HTTP {status}")
    for issue in issues or []:  # newest first - the rolling issue is ours
        if issue.get("title") == ISSUE_TITLE and "pull_request" not in issue:
            return issue["number"]
    return None


def extract_posting_urls(body: str) -> set[str]:
    """Full posting URLs already reported in a comment, across both boards.
    Must stay in lockstep with the URL shapes classify()/collect_postings()
    produce: full URLs, so split_new's set membership is an exact match
    (fragment extraction would never match and re-alert everything daily).
    Run links, board homepages, and keyword-file references are ignored."""
    urls = set(re.findall(
        r"https?://www\.realworkfromanywhere\.com/jobs/[a-z0-9-]+", body))
    urls |= set(re.findall(
        r"https?://www\.moaijobs\.com/job/[a-z0-9-]+", body))
    return urls


def fetch_comments(issue: int) -> list[dict]:
    """All comments oldest-first with their posting URLs extracted. Errors
    propagate - a failed read must not let the run misclassify history as
    unseen and re-alert everything. Paginated at the API maximum (100)."""
    comments: list[dict] = []
    page = 1
    while True:
        status, batch = _gh_request(
            "GET", f"issues/{issue}/comments?per_page=100&page={page}")
        if status >= 400:
            raise RuntimeError(
                f"GitHub comments fetch failed with HTTP {status}")
        if not batch:
            break
        comments.extend({"id": c["id"], "created": c["created_at"],
                         "body": c["body"]} for c in batch)
        if len(batch) < 100:
            break
        page += 1
    comments.sort(key=lambda c: c["created"])  # oldest-first
    for c in comments:
        c["jobs"] = extract_posting_urls(c["body"])
    return comments


def post_comment(issue: int, body: str) -> None:
    status, _ = _gh_request("POST", f"issues/{issue}/comments", {"body": body})
    if status >= 400:
        raise RuntimeError(f"GitHub comment post failed with HTTP {status}")


# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------

def geo_tag(card: dict) -> str:
    """Tag suffix for a rendered line: only the two labels, never unknown -
    an untagged MoAIJobs posting simply shows no location claim."""
    return GEO_LABELS.get(card.get("geo"), "")


def render_section(cards: list[dict]) -> list[str]:
    lines: list[str] = []
    for c in cards:
        bits = [f"[{c['title']}]({c['url']})"]
        bits.append(c["company"] or "—")
        bits.append(f"`{c['category']}`")
        if c["salary"]:
            bits.append(c["salary"])
        if c["date"]:
            bits.append(f"({c['date']})")
        if c["tags"]:
            bits.append(" ".join(f"`{t}`" for t in c["tags"][:6]))
        tag = geo_tag(c)
        if tag:
            bits.append(tag)
        lines.append(f"- {' · '.join(bits)}")
    return lines


def render_comment(run_url: str, checked: str, new: list[dict],
                   still_open: list[dict], backlog: list[dict],
                   bootstrapped: bool, notes: list[str] | None = None,
                   summary: str | None = None,
                   weekly_payload: str | None = None) -> str:
    parts: list[str] = [f"## Job alert — {checked}", ""]
    if summary:
        parts += [f"> {summary}", ""]
    if weekly_payload:
        parts += [weekly_payload, ""]
    for note in notes or []:
        parts += [f"> ⚠️ {note}", ""]
    if bootstrapped:
        parts += ["*Initial sweep at alert setup — everything below existed "
                  "before the alert went live; after this, only new postings "
                  "get their own comment.*", ""]
        parts += [HOW_TO_READ, ""]
    if new:
        parts += [f"**{len(new)} new Priority-1 match(es):**", ""]
        parts += render_section(new)
    elif still_open:
        parts += [f"No new matches today — {len(still_open)} earlier "
                  "match(es) still open and inside the window:"]
        parts += [f"  - {c['title']} ([posting]({c['url']}))" for c in still_open]
    else:
        parts += ["No new matches today."]
    if backlog:
        parts += ["", f"<details><summary>Matched, older than the window "
                      f"({len(backlog)}) — listed once, then only in the "
                      f"comment history</summary>", ""]
        parts += render_section(backlog[:20])
        if len(backlog) > 20:
            parts += [f"- …and {len(backlog) - 20} more"]
        parts += ["", "</details>"]
    parts += [
        "",
        "---",
        f"*Report only — the alert never applies for you. Keywords: "
        f"`tools/job_alert_keywords.txt` (Priority 1 of "
        f"`.claude/skills/job-scraper/search-queries.md`) · boards: "
        f"[Real Work From Anywhere]({BASE_URL}) · "
        f"[MoAIJobs]({MOAI_BASE_URL}) · [run]({run_url}) · "
        f"tags: 🌍 EU/UK ok / 🇺🇸 US-only · "
        "stop it: disable the `Job alert` workflow.*",
    ]
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def _run_weekly(args: argparse.Namespace) -> int:
    """Sunday cron: fetch the issue's comments, fold the past 7 days of
    hidden payloads into one trend comment, and post it. In dry-run the
    would-be summary goes to stdout and nothing is touched. Silence is a
    valid outcome only when the issue does not exist yet (no dailies ever
    ran); an existing issue with zero payload comments still posts, so a
    broken embed is visible rather than silent."""
    issue = find_issue(args.force_issue)
    if issue is None:
        print("job alert weekly: no rolling issue found - nothing to "
              "summarize yet", file=sys.stderr)
        return 0
    comments = fetch_comments(issue)
    today = datetime.date.today()
    body = weekly_summary(comments, today, args.run_url)
    if args.dry_run:
        sys.stdout.write(body)
        payloads = extract_weekly_payloads(comments)
        agg = aggregate_week(payloads, today)
        print(f"[weekly dry run] issue #{issue}: {len(comments)} comments, "
              f"{len(payloads)} with weekly payloads, "
              f"total_fresh={agg['total_fresh']} "
              f"backlog={agg['total_backlog']}", file=sys.stderr)
        return 0
    post_comment(issue, body)
    print(f"job alert weekly: posted trend summary to issue #{issue}",
          file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Daily Priority-1 job alert (report-only, state in the "
                    "rolling issue's comments)")
    parser.add_argument("--max-age-days", type=int, default=3,
                        help="postings newer than this many days count as "
                             "NEW candidates (default 3)")
    parser.add_argument("--run-url", default="(unknown run)",
                        help="link to the triggering workflow run, for the footer")
    parser.add_argument("--force-issue", type=int, default=None,
                        help="use this issue number instead of title lookup")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the comment markdown to stdout; touch nothing")
    parser.add_argument("--weekly", action="store_true",
                        help="post the weekly trend summary instead of the "
                             "daily sweep (for the Sunday cron)")
    args = parser.parse_args(argv)

    if args.weekly:
        return _run_weekly(args)

    entries = load_keyword_entries()
    pattern = keyword_pattern([term for term, _geo in entries])

    cards, notes = collect_postings()
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    if not cards:
        # Fail loudly: a fully green run on broken sources is the silent
        # death this alert must never have. GitHub notifies on workflow failure.
        print("job alert: ZERO postings parsed from ALL sources - every feed "
              "is unreachable or markup changed. Check the url-reference.md "
              "anchors of both portal skills.", file=sys.stderr)
        return 1

    fresh, backlog = classify(cards, pattern, args.max_age_days)

    if args.dry_run:
        comment = render_comment(args.run_url, "DRY RUN", fresh, [], backlog,
                                 bootstrapped=False, notes=notes)
        sys.stdout.write(comment)
        print(f"[dry run] {len(cards)} postings scanned, {len(entries)} keywords: "
              f"fresh={len(fresh)} backlog={len(backlog)} "
              f"notes={len(notes)}", file=sys.stderr)
        return 0

    issue = find_issue(args.force_issue)
    if issue is None:
        body = ("Rolling alert issue for Priority-1 keyword matches on "
                f"[Real Work From Anywhere]({BASE_URL}) and "
                f"[MoAIJobs]({MOAI_BASE_URL}).\n\nEach daily run comments "
                "only when there is something new. Report only - it never "
                "applies for you. Keywords live in "
                "`tools/job_alert_keywords.txt`.")
        created = _gh_request("POST", "issues",
                              {"title": ISSUE_TITLE, "body": body})
        if created[0] >= 400 or not created[1]:
            raise RuntimeError(
                f"GitHub issue creation failed with HTTP {created[0]}")
        issue = created[1]["number"]
        print(f"created rolling issue #{issue}", file=sys.stderr)

    comments = fetch_comments(issue)
    already_seen: set[str] = set()
    for c in comments:
        already_seen |= c["jobs"]

    first_run = not comments
    new, still_open = split_new(fresh, already_seen)

    if not first_run and not new and not still_open:
        # Nothing fresh and nothing to re-show: keep the issue quiet. The
        # backlog already appeared once in a previous comment's details block.
        print(f"job alert: {len(fresh)} fresh + {len(backlog)} backlog "
              f"match(es), all already reported - issue left quiet",
              file=sys.stderr)
        return 0

    checked = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    payload, _version = build_weekly_payload(checked, cards, fresh, backlog)
    body = render_comment(args.run_url, checked, new, still_open, backlog,
                          bootstrapped=first_run, notes=notes,
                          weekly_payload=payload)
    post_comment(issue, body)
    print(f"job alert: posted to issue #{issue} - {len(new)} new, "
          f"{len(still_open)} still open, {len(backlog)} older backlog",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
