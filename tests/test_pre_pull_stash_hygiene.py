"""Fail while a pre-pull stash entry sits forgotten for more than 24 hours.

The fork's pre-pull script (_CORRER_ISTO_EM_VEZ_DE_GIT_PULL.ps1) stashes the
working tree (including untracked files) before `git pull --ff-only`, then
pops the stash back. When the pop never happens - the pull fails and the run
is abandoned, the pop conflicts and is left "for manual recovery", or the
pull is simply run by hand instead of through the script - the stash keeps
the only copy of that work, and nothing in the repo ever mentions it again.
That is how a full day of work (two portal skills, the daily job alert, and
the fork personalization) ended up locked in stash@{0} on 2026-09-05 and had
to be restored file by file from the stash's trees.

This guard fails while any stash entry whose message comes from the pre-pull
script ("pre-pull automatico ...") is older than 24 hours (override with
PRE_PULL_STASH_MAX_AGE_HOURS), so the next unittest run surfaces the orphan
before it is forgotten. Non-pre-pull stashes older than the threshold print
a warning but do not fail - they may be intentional. GitHub CI runners clone
fresh and have no stash at all, so the guard is trivially green there; it
exists to bite on the machine where the risk actually lives.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAX_AGE_HOURS = 24.0
PRE_PULL_MARKER = "pre-pull automatico"


def max_age_hours() -> float:
    """Threshold in hours; PRE_PULL_STASH_MAX_AGE_HOURS overrides the 24h
    default so triage can temporarily widen the window."""
    raw = os.environ.get("PRE_PULL_STASH_MAX_AGE_HOURS")
    if not raw:
        return DEFAULT_MAX_AGE_HOURS
    try:
        value = float(raw)
    except ValueError:
        raise SystemExit(
            f"PRE_PULL_STASH_MAX_AGE_HOURS must be a number, got {raw!r}")
    if value < 0:
        raise SystemExit("PRE_PULL_STASH_MAX_AGE_HOURS must be >= 0")
    return value


def parse_stash_list(text: str) -> list[dict]:
    """Parse `git stash list --format=...` output into entries.

    Fields are separated by \\x1f (unit separator) and records by \\x1e
    (record separator), so subjects containing | or newlines cannot break
    the parse. Malformed records are dropped rather than guessed at.
    """
    entries: list[dict] = []
    for record in text.split("\x1e"):
        record = record.strip("\r\n")
        if not record.strip():
            continue
        fields = record.split("\x1f")
        if len(fields) != 4:
            continue
        sha, ref, date, subject = (f.strip() for f in fields)
        entries.append({"sha": sha, "ref": ref, "date": date,
                        "subject": subject})
    return entries


def stash_list(repo_root: Path = REPO_ROOT) -> list[dict]:
    out = subprocess.run(
        ["git", "stash", "list",
         "--format=%H%x1f%gd%x1f%cI%x1f%gs%x1e"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    return parse_stash_list(out.stdout)


def age_hours(entry: dict, now: datetime.datetime) -> float | None:
    """Hours since the stash commit was created; None when unparseable."""
    try:
        created = datetime.datetime.fromisoformat(entry["date"])
    except (TypeError, ValueError):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, (now - created).total_seconds() / 3600.0)


def forgotten_pre_pull(entries: list[dict], now: datetime.datetime,
                       threshold_hours: float
                       ) -> tuple[list[dict], list[dict]]:
    """Split entries into (forgotten pre-pull beyond the threshold, other old
    stashes). A pre-pull stash with an unparseable date is flagged
    conservatively: its age cannot be proven fresh."""
    forgotten: list[dict] = []
    other_old: list[dict] = []
    for entry in entries:
        hours = age_hours(entry, now)
        is_pre_pull = PRE_PULL_MARKER in entry["subject"].lower()
        if is_pre_pull:
            if hours is None or hours > threshold_hours:
                forgotten.append({**entry, "age_hours": hours})
        elif hours is not None and hours > threshold_hours:
            other_old.append({**entry, "age_hours": hours})
    return forgotten, other_old


class PureLogicTests(unittest.TestCase):
    NOW = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)

    @staticmethod
    def entry(ref: str, subject: str, iso: str) -> dict:
        return {"sha": "abc123", "ref": ref, "date": iso, "subject": subject}

    def test_old_pre_pull_entry_is_forgotten(self):
        old = self.entry("stash@{0}", "pre-pull automatico 20260904-120000",
                         "2026-09-04T12:00:00+01:00")
        forgotten, other = forgotten_pre_pull([old], self.NOW, 24.0)
        self.assertEqual([e["ref"] for e in forgotten], ["stash@{0}"])
        self.assertEqual(other, [])

    def test_recent_pre_pull_entry_passes(self):
        recent = self.entry("stash@{0}", "pre-pull automatico 20260906-100000",
                            "2026-09-06T10:00:00+01:00")
        forgotten, other = forgotten_pre_pull([recent], self.NOW, 24.0)
        self.assertEqual((forgotten, other), ([], []))

    def test_unrelated_stashes_warn_but_do_not_fail(self):
        manual = self.entry("stash@{0}", "WIP: experiment",
                            "2026-01-01T00:00:00+00:00")
        forgotten, other = forgotten_pre_pull([manual], self.NOW, 24.0)
        self.assertEqual(forgotten, [])
        self.assertEqual([e["ref"] for e in other], ["stash@{0}"])

    def test_unparseable_pre_pull_date_is_flagged_conservatively(self):
        broken = self.entry("stash@{0}", "pre-pull automatico x", "not-a-date")
        forgotten, _ = forgotten_pre_pull([broken], self.NOW, 24.0)
        self.assertEqual(len(forgotten), 1)
        self.assertIsNone(forgotten[0]["age_hours"])

    def test_parse_stash_list_roundtrip(self):
        text = ("a1\x1fstash@{0}\x1f2026-09-04T12:00:00+01:00\x1f"
                "pre-pull automatico 20260904-120000\x1e"
                "b2\x1fstash@{1}\x1f2026-08-23T14:41:59+01:00\x1f"
                "pre-pull automatico 20260823-144159\x1e\n")
        entries = parse_stash_list(text)
        self.assertEqual([e["subject"] for e in entries],
                         ["pre-pull automatico 20260904-120000",
                          "pre-pull automatico 20260823-144159"])
        self.assertEqual([e["ref"] for e in entries], ["stash@{0}", "stash@{1}"])

    def test_threshold_zero_still_passes_a_just_created_stash(self):
        fresh = self.entry("stash@{0}", "pre-pull automatico now",
                           self.NOW.isoformat())
        forgotten, _ = forgotten_pre_pull([fresh], self.NOW, 0.0)
        self.assertEqual(forgotten, [])


class LiveRepoGuardTests(unittest.TestCase):
    """The actual guard. On a fresh CI clone `git stash list` returns empty
    and the check is trivially green; on a machine that actually has stashes
    (the only place the forgotten-stash failure mode exists) it bites."""

    def setUp(self):
        try:
            self.entries = stash_list()
        except FileNotFoundError:
            self.skipTest("git not available")
        except subprocess.CalledProcessError as exc:
            if "not a git repository" in (exc.stderr or "").lower():
                self.skipTest("not a git repository")
            self.skipTest(f"git stash list failed: {exc.stderr}".strip())

    def test_no_forgotten_pre_pull_stash(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        threshold = max_age_hours()
        forgotten, other_old = forgotten_pre_pull(self.entries, now, threshold)
        for entry in other_old:
            print(f"note: non-pre-pull stash older than {threshold:g}h "
                  f"(warning only): {entry['ref']} - {entry['subject']!r} "
                  f"({entry['age_hours']:.0f}h)", file=sys.stderr)
        if not forgotten:
            return
        lines = [
            f"{len(forgotten)} pre-pull stash(es) older than {threshold:g}h - "
            "the pre-pull script saved the working tree and never restored "
            "it. Triage now, before the stash is forgotten:",
        ]
        for entry in forgotten:
            age = (f"{entry['age_hours']:.0f}h"
                   if entry["age_hours"] is not None else "unknown age")
            lines.append(f"  {entry['ref']} ({age}) - {entry['subject']}")
        lines += [
            "",
            "  Inspect:  git stash show --include-untracked -p stash@{N}",
            "  Restore:  git stash pop stash@{N}   (or git stash apply)",
            "  Discard:  git stash drop stash@{N}   (only after triage!)",
            "",
            "  A forgotten pre-pull stash silently held the only copy of a "
            "full day of work on 2026-09-05. Override the threshold with "
            "PRE_PULL_STASH_MAX_AGE_HOURS while triaging.",
        ]
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
