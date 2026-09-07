import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "job-alert.yml"
SCRIPT = REPO_ROOT / "tools" / "job_alert.py"
KEYWORDS = REPO_ROOT / "tools" / "job_alert_keywords.txt"
UPSTREAM_SLUG = "MadsLorentzen/ai-job-search"

import job_alert  # noqa: E402  (path set up above)


CARD = (
    '<a href="/jobs/product-engineer-safetywing-7580" class="block w-full '
    'rounded-lg bg-base-100 ring-1 ring-inset ring-base-300 "><div>'
    '<h3 class="text-xl">Product Engineer</h3>'
    '<p class="text-base truncate font-medium text-base-content/90">SafetyWing</p>'
    '<span class="hidden md:block shrink-0 text-sm whitespace-nowrap '
    'text-base-content/80">1 day ago</span>'
    '<span class="whitespace-nowrap">$119,900 - $193,200 USD</span>'
    '<span class="badge border-base-300">llm</span>'
    '<span class="badge border-base-300">python</span>'
    "</div></a>"
)


class KeywordTests(unittest.TestCase):
    def test_load_ignores_comments_and_blanks(self):
        terms = job_alert.load_keywords(KEYWORDS)
        self.assertIn("llm", terms)
        self.assertFalse(any(t.startswith("#") for t in terms))

    def test_word_boundaries(self):
        pat = job_alert.keyword_pattern(["llm", "ai"])
        self.assertIsNotNone(pat.search("LLM Engineer"))
        self.assertIsNone(pat.search("email"))
        self.assertIsNone(pat.search("maintain"))
        self.assertIsNotNone(pat.search("AI Product Engineer"))

    def test_multiword_term(self):
        pat = job_alert.keyword_pattern(["applied ai"])
        self.assertIsNotNone(pat.search("Senior Applied AI Engineer"))
        self.assertIsNone(pat.search("applied"))

    def test_matches_tags_and_company_not_just_title(self):
        pat = job_alert.keyword_pattern(["python", "safetywing"])
        card = job_alert.parse_cards(CARD, "product")[0]
        hay = " ".join([card["title"], card["company"] or "", *card["tags"]])
        self.assertIsNotNone(pat.search(hay))


class ParseTests(unittest.TestCase):
    def test_parses_full_card(self):
        cards = job_alert.parse_cards(CARD, "product")
        self.assertEqual(len(cards), 1)
        c = cards[0]
        self.assertEqual(c["id"], "7580")
        self.assertEqual(c["title"], "Product Engineer")
        self.assertEqual(c["company"], "SafetyWing")
        self.assertEqual(c["date"], "1 day ago")
        self.assertEqual(c["salary"], "$119,900 - $193,200 USD")
        self.assertEqual(c["tags"], ["llm", "python"])
        self.assertEqual(c["url"],
                         "https://www.realworkfromanywhere.com/jobs/product-engineer-safetywing-7580")

    def test_malformed_card_is_skipped_not_fatal(self):
        broken = CARD.replace("7580", "abc")  # no trailing numeric id
        cards = job_alert.parse_cards(CARD + broken, "product")
        self.assertEqual([c["id"] for c in cards], ["7580"])

    def test_new_and_relative_dates(self):
        self.assertEqual(job_alert.relative_date_to_days("New"), 0)
        self.assertEqual(job_alert.relative_date_to_days("2 weeks ago"), 14)
        self.assertIsNone(job_alert.relative_date_to_days("recently"))

    def test_unparseable_date_counts_as_fresh(self):
        # A card whose date cannot be read must not be silently dropped by
        # the age filter - the seen-set is what prevents re-alerts.
        cards = [{"title": "x", "company": None, "tags": [], "date": "???", "url": "u"}]
        fresh, _ = job_alert.classify(cards, job_alert.keyword_pattern(["x"]), 3)
        self.assertEqual(len(fresh), 1)


class ClassifyTests(unittest.TestCase):
    def _cards(self, *ages):
        return [
            {"title": f"LLM Engineer {i}", "company": "Acme", "tags": [],
             "date": age, "url": f"https://x/jobs/a-{i}"}
            for i, age in enumerate(ages)
        ]

    def test_window_split(self):
        fresh, backlog = job_alert.classify(
            self._cards("1 day ago", "2 weeks ago", "New"),
            job_alert.keyword_pattern(["llm"]), 3)
        self.assertEqual(len(fresh), 2)
        self.assertEqual(len(backlog), 1)

    def test_seen_set_splits_new_from_still_open(self):
        fresh = self._cards("1 day ago")
        seen = {fresh[0]["url"]}
        new, still_open = job_alert.split_new(fresh, seen)
        self.assertEqual(new, [])
        self.assertEqual(len(still_open), 1)


MOAI_RSS = (
    '<?xml version="1.0"?><rss><channel>'
    "<item>"
    "<title><![CDATA[Applied AI, Research Engineer at Anthropic]]></title>"
    "<link><![CDATA[https://www.moaijobs.com/job/applied-ai-research-engineer-anthropic-5585]]></link>"
    "<pubDate>Fri, 04 Sep 2026 22:13:05 GMT</pubDate>"
    '<description><![CDATA[&lt;p&gt;&lt;strong&gt;Company:&lt;/strong&gt; Anthropic&lt;/p>"]]></description>'
    "</item>"
    "<item>"
    "<title><![CDATA[Engineer at Scale at Cohere]]></title>"
    "<link><![CDATA[https://www.moaijobs.com/job/engineer-at-scale-cohere-123]]></link>"
    "<pubDate>Fri, 04 Sep 2026 21:00:00 GMT</pubDate>"
    "<description><![CDATA[x]]></description>"
    "</item>"
    "<item>"
    "<title><![CDATA[No Id In Link at Acme]]></title>"
    "<link><![CDATA[https://www.moaijobs.com/job/no-numeric-id]]></link>"
    "<pubDate>Fri, 04 Sep 2026 20:00:00 GMT</pubDate>"
    "<description><![CDATA[x]]></description>"
    "</item>"
    "</channel></rss>"
)


class MoaiRssTests(unittest.TestCase):
    def test_parses_items_and_splits_company_off_last_at(self):
        cards = job_alert.parse_moai_rss(MOAI_RSS)
        self.assertEqual(len(cards), 2)  # the id-less item is skipped
        self.assertEqual(cards[0]["title"], "Applied AI, Research Engineer")
        self.assertEqual(cards[0]["company"], "Anthropic")
        self.assertEqual(cards[0]["id"], "5585")
        self.assertEqual(cards[0]["category"], "moaijobs")
        self.assertEqual(cards[0]["url"],
                         "https://www.moaijobs.com/job/applied-ai-research-engineer-anthropic-5585")
        # A role containing " at " must not be mangled.
        self.assertEqual(cards[1]["title"], "Engineer at Scale")
        self.assertEqual(cards[1]["company"], "Cohere")

    def test_recent_pubdate_counts_as_fresh(self):
        # The feed's absolute pubDate is converted to a relative age; these
        # items are 1-2 days old, so they sit inside a 3-day window.
        cards = job_alert.parse_moai_rss(MOAI_RSS)
        self.assertIsNotNone(cards[0]["date"])
        fresh, _ = job_alert.classify(cards, job_alert.keyword_pattern(["llm", "research"]), 3)
        self.assertEqual(len(fresh), 1)  # only the Research Engineer matches

    def test_old_pubdate_ages_out_of_the_window(self):
        # Without real ages, RSS postings would stay "fresh" forever and
        # re-list every past match in each daily comment.
        xml = MOAI_RSS.replace(
            "Fri, 04 Sep 2026 22:13:05 GMT", "Tue, 01 Jul 2026 12:00:00 GMT")
        cards = job_alert.parse_moai_rss(xml)
        self.assertIn("days ago", cards[0]["date"])
        fresh, backlog = job_alert.classify(
            cards, job_alert.keyword_pattern(["research"]), 3)
        self.assertEqual(fresh, [])
        self.assertEqual(len(backlog), 1)

    def test_missing_pubdate_counts_as_fresh(self):
        xml = MOAI_RSS.replace("<pubDate>Fri, 04 Sep 2026 22:13:05 GMT</pubDate>", "")
        cards = job_alert.parse_moai_rss(xml)
        self.assertIsNone(cards[0]["date"])
        fresh, _ = job_alert.classify(cards, job_alert.keyword_pattern(["research"]), 3)
        self.assertEqual(len(fresh), 1)


class ExtractUrlsTests(unittest.TestCase):
    def test_extracts_both_board_shapes(self):
        body = ("- [Product Engineer](https://www.realworkfromanywhere.com/jobs/product-engineer-safetywing-7580)\n"
                "- [Research Engineer](https://www.moaijobs.com/job/applied-ai-research-engineer-anthropic-5585)")
        urls = job_alert.extract_posting_urls(body)
        self.assertEqual(urls, {
            "https://www.realworkfromanywhere.com/jobs/product-engineer-safetywing-7580",
            "https://www.moaijobs.com/job/applied-ai-research-engineer-anthropic-5585",
        })

    def test_ignores_homepages_run_links_and_footers(self):
        body = ("boards: [Real Work From Anywhere](https://www.realworkfromanywhere.com) · "
                "[MoAIJobs](https://www.moaijobs.com) · "
                "[run](https://github.com/example-owner/ai-job-search/actions/runs/123)")
        self.assertEqual(job_alert.extract_posting_urls(body), set())

    def test_roundtrip_with_rendered_card(self):
        card = job_alert.parse_moai_rss(MOAI_RSS)[0]
        body = f"- [{card['title']}]({card['url']})"
        self.assertIn(card["url"], job_alert.extract_posting_urls(body))


class RenderTests(unittest.TestCase):
    def test_comment_contains_matches_and_disclaimer(self):
        cards = job_alert.parse_cards(CARD, "product")
        body = job_alert.render_comment("http://run", "2026-09-05", cards, [], [],
                                        bootstrapped=False)
        self.assertIn("1 new Priority-1 match(es)", body)
        self.assertIn("Product Engineer", body)
        self.assertIn("Report only", body)

    def test_backlog_is_collapsed(self):
        backlog = job_alert.parse_cards(CARD, "product")
        body = job_alert.render_comment("http://run", "d", [], [], backlog,
                                        bootstrapped=False)
        self.assertIn("<details>", body)

    def test_bootstrapped_note(self):
        body = job_alert.render_comment("http://run", "d", [], [], [],
                                        bootstrapped=True)
        self.assertIn("Initial sweep", body)
        # The setup must stay self-documenting: every future rolling issue's
        # first comment explains how to read the alerts.
        self.assertIn("How to read this issue", body)
        self.assertIn("tools/job_alert_keywords.txt", body)

    def test_source_notes_render_as_warnings(self):
        body = job_alert.render_comment("http://run", "d", [], [], [],
                                        bootstrapped=False,
                                        notes=["moaijobs: RSS fetch failed, skipped: boom"])
        self.assertIn("⚠️ moaijobs: RSS fetch failed", body)

    def test_footer_covers_both_boards(self):
        body = job_alert.render_comment("http://run", "d", [], [], [],
                                        bootstrapped=False)
        self.assertIn("boards:", body)
        self.assertIn("MoAIJobs", body)


class WorkflowGuardTests(unittest.TestCase):
    """Same invariants test_upstream_triage.py pins for upstream-watch.yml."""

    def test_workflow_is_guarded_against_upstream(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(f"github.repository != '{UPSTREAM_SLUG}'", text)

    def test_workflow_uses_builtin_token_only(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("GH_TOKEN: ${{ github.token }}", text)
        self.assertNotIn("secrets.", text)

    def test_actions_are_sha_pinned(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- uses:") or stripped.startswith("uses:"):
                ref = stripped.split("uses:", 1)[1].strip()
                sha = ref.split("@", 1)[1].split()[0]
                self.assertRegex(sha, r"^[0-9a-f]{40}$",
                                 f"action not SHA-pinned: {ref}")

    def test_issues_write_is_scoped(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("issues: write", text)
        self.assertIn("contents: read", text)


import datetime  # noqa: E402  (used by the weekly tests below)


def _weekly_card(url, category, title="LLM Engineer"):
    return {"id": url.rstrip("/").rsplit("-", 1)[-1], "title": title,
            "company": "Acme", "date": "1 day ago", "salary": None,
            "tags": [], "url": url, "category": category}


class WeeklyPayloadTests(unittest.TestCase):
    def _cards(self):
        return [
            _weekly_card("https://www.realworkfromanywhere.com/jobs/product-engineer-safetywing-7580",
                         "product", "Product Engineer"),
            _weekly_card("https://www.moaijobs.com/job/applied-ai-research-engineer-anthropic-5585",
                         "moaijobs", "Applied AI, Research Engineer"),
            _weekly_card("https://www.moaijobs.com/job/llm-engineer-acme-9",
                         "moaijobs"),
        ]

    def test_payload_roundtrip(self):
        cards = self._cards()
        payload, version = job_alert.build_weekly_payload(
            "2026-09-06 08:00 UTC", cards, cards[:2], cards[2:])
        self.assertEqual(version, 2)
        data = job_alert.extract_weekly_payloads(
            [{"id": 1, "created": "2026-09-06T08:01:00Z", "body": payload}])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["checked"], "2026-09-06 08:00 UTC")
        self.assertEqual({b["board"] for b in data[0]["buckets"]},
                         {"product", "moaijobs"})
        moai = next(b for b in data[0]["buckets"] if b["board"] == "moaijobs")
        self.assertEqual(moai["fresh"], 1)
        self.assertEqual(moai["backlog"], 1)
        self.assertEqual(moai["fresh_urls"],
                         ["https://www.moaijobs.com/job/applied-ai-research-engineer-anthropic-5585"])

    def test_payload_survives_render_comment(self):
        cards = self._cards()
        payload, _ = job_alert.build_weekly_payload(
            "2026-09-06 08:00 UTC", cards, cards[:2], cards[2:])
        body = job_alert.render_comment(
            "http://run", "2026-09-06 08:00 UTC", cards[:2], [], cards[2:],
            bootstrapped=False, weekly_payload=payload)
        data = job_alert.extract_weekly_payloads(
            [{"id": 2, "created": "2026-09-06T08:01:00Z", "body": body}])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["buckets"][0]["board"], "moaijobs")

    def test_payload_hidden_from_rendered_text(self):
        # The payload is an HTML comment: GitHub never renders it, so the
        # daily comment stays clean even though the body carries the counts.
        cards = self._cards()
        payload, _ = job_alert.build_weekly_payload(
            "2026-09-06 08:00 UTC", cards, cards, [])
        body = job_alert.render_comment(
            "http://run", "d", cards, [], [], bootstrapped=False,
            weekly_payload=payload)
        self.assertTrue(payload.startswith("<!-- weekly-counts "))
        self.assertIn(payload, body)
        rendered = body.replace(payload, "")
        self.assertNotIn("weekly-counts", rendered)
        self.assertNotIn("scanned", rendered)

    def test_malformed_and_missing_payloads_skipped(self):
        comments = [
            {"id": 3, "created": "x", "body": "<!-- weekly-counts @@bad@@-->"},
            {"id": 4, "created": "x", "body": "no payload here"},
        ]
        self.assertEqual(job_alert.extract_weekly_payloads(comments), [])


class WeeklyAggregateTests(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 6)  # a Sunday

    @staticmethod
    def _bucket(day, board, scanned, fresh, backlog, fresh_urls=None):
        return {"board": board, "day": day, "scanned": scanned, "fresh": fresh,
                "backlog": backlog, "fresh_urls": fresh_urls or []}

    def test_cross_run_fresh_dedupe_by_url(self):
        url = "https://www.moaijobs.com/job/llm-engineer-acme-9"
        payloads = [
            {"created": "2026-09-04T07:05:00Z", "v": 2, "checked": "x",
             "buckets": [self._bucket("2026-09-04", "moaijobs", 300, 1, 5, [url])]},
            {"created": "2026-09-05T07:05:00Z", "v": 2, "checked": "x",
             "buckets": [self._bucket("2026-09-05", "moaijobs", 310, 1, 5, [url])]},
        ]
        agg = job_alert.aggregate_week(payloads, self.TODAY)
        self.assertEqual(agg["total_fresh"], 1)  # same URL across runs -> once
        self.assertEqual(agg["runs"], 2)
        self.assertEqual(agg["days_with_data"], 2)

    def test_v1_payload_counts_fresh_per_run(self):
        bucket = {"board": "moaijobs", "day": "2026-09-04", "scanned": 300,
                  "fresh": 1, "backlog": 5}
        agg = job_alert.aggregate_week(
            [{"created": "2026-09-04T07:05:00Z", "v": 1, "checked": "x",
              "buckets": [dict(bucket), dict(bucket, day="2026-09-05")]}],
            self.TODAY)
        self.assertEqual(agg["total_fresh"], 2)  # v1: no URLs, no dedupe

    def test_out_of_window_and_unknown_days_dropped(self):
        agg = job_alert.aggregate_week(
            [{"created": "2026-08-01T07:00:00Z", "v": 2, "checked": "x",
              "buckets": [
                  self._bucket("2026-08-01", "moaijobs", 300, 1, 5, ["u"]),
                  self._bucket("2026-09-20", "moaijobs", 300, 1, 5, ["v"]),
                  {"board": "product", "day": "-", "scanned": 1,
                   "fresh": 1, "backlog": 0, "fresh_urls": ["w"]},
              ]}],
            self.TODAY)
        self.assertEqual(agg["total_fresh"], 0)
        self.assertEqual(agg["per_category"], {})

    def test_board_folding_and_day_from_created(self):
        # "day" missing -> falls back to the comment's created date; RWFA
        # categories fold into one board, moaijobs stays its own.
        bucket = {"board": "fullstack", "scanned": 10, "fresh": 1, "backlog": 2,
                  "fresh_urls": ["https://www.realworkfromanywhere.com/jobs/x-1"]}
        agg = job_alert.aggregate_week(
            [{"created": "2026-09-05T07:05:00Z", "v": 2, "checked": "x",
              "buckets": [bucket, dict(bucket, board="moaijobs")]}],
            self.TODAY)
        self.assertEqual(set(agg["per_board"]),
                         {"realworkfromanywhere", "moaijobs"})
        self.assertEqual(agg["per_board"]["realworkfromanywhere"]["fresh"], 1)
        self.assertEqual(agg["days_with_data"], 1)
        self.assertEqual(agg["total_backlog"], 4)

    def test_render_weekly_comment(self):
        payloads = [
            {"created": "2026-09-05T07:05:00Z", "v": 2, "checked": "x",
             "buckets": [
                 self._bucket("2026-09-05", "moaijobs", 310, 2, 5,
                              ["https://www.moaijobs.com/job/a-1",
                               "https://www.moaijobs.com/job/b-2"]),
                 self._bucket("2026-09-05", "product", 62, 1, 0,
                              ["https://www.realworkfromanywhere.com/jobs/p-3"]),
             ]},
        ]
        body = job_alert.render_weekly_comment(payloads, self.TODAY, "http://run")
        self.assertIn("Weekly trend \u2014 2026-08-31 to 2026-09-06", body)
        self.assertIn("**3 new Priority-1 match(es)**", body)
        self.assertIn("MoAIJobs: **2**", body)
        self.assertIn("Real Work From Anywhere: **1**", body)
        self.assertIn("moaijobs: 2", body)
        self.assertIn("product: 1", body)
        self.assertIn("\u2588", body)  # per-day bar
        self.assertIn("backlog seen during the week", body)

    def test_render_weekly_edge_cases(self):
        # no payload comments yet
        self.assertIn("No weekly counts found",
                      job_alert.render_weekly_comment([], self.TODAY, "r"))
        # sweeps ran all week but nothing matched
        zero = job_alert.render_weekly_comment(
            [{"created": "2026-09-05T07:05:00Z", "v": 2, "checked": "x",
              "buckets": [self._bucket("2026-09-05", "moaijobs", 310, 0, 5)]}],
            self.TODAY, "r")
        self.assertIn("**0 new Priority-1 match(es)**", zero)
        # payloads exist but every bucket is outside the window
        empty = job_alert.render_weekly_comment(
            [{"created": "2026-08-01T07:00:00Z", "v": 2, "checked": "x",
              "buckets": [self._bucket("2026-08-01", "moaijobs", 1, 1, 0, ["u"])]}],
            self.TODAY, "r")
        self.assertIn("No Priority-1 matches in this week's 1 daily", empty)

    def test_weekly_summary_end_to_end(self):
        cards = job_alert.parse_cards(CARD, "product")
        payload, _ = job_alert.build_weekly_payload(
            "2026-09-05 07:05 UTC", cards, cards, [])
        comments = [{"id": 9, "created": "2026-09-05T07:05:00Z", "body": payload}]
        body = job_alert.weekly_summary(comments, self.TODAY, "http://run")
        self.assertIn("**1 new Priority-1 match(es)**", body)
        self.assertIn("product: 1", body)


class GeoTagTests(unittest.TestCase):
    """Optional location/geo tags: keyword-line suffixes, location -> tag
    classification, RSS Location extraction, and the rendered output."""

    def test_parse_keyword_line_suffixes(self):
        self.assertEqual(job_alert.parse_keyword_line("llm"), ("llm", None))
        self.assertEqual(job_alert.parse_keyword_line("  applied ai  "),
                         ("applied ai", None))
        self.assertEqual(
            job_alert.parse_keyword_line("digital humanities | anywhere"),
            ("digital humanities", "anywhere"))
        self.assertEqual(job_alert.parse_keyword_line("RAG | us-only"),
                         ("rag", "us-only"))
        # An unrecognized suffix keeps the whole line as the term.
        self.assertEqual(job_alert.parse_keyword_line("c++ | junior"),
                         ("c++ | junior", None))

    def test_real_keywords_file_loads_with_entries(self):
        entries = job_alert.load_keyword_entries(job_alert.KEYWORDS_FILE)
        terms = [term for term, _geo in entries]
        self.assertIn("llm", terms)
        overrides = {term: geo for term, geo in entries if geo}
        self.assertEqual(overrides.get("digital humanities"), "anywhere")
        self.assertEqual(overrides.get("cultural heritage"), "anywhere")
        # The pattern must be built from the stripped terms only.
        self.assertIsNotNone(
            job_alert.keyword_pattern(terms).search("LLM Engineer"))

    def test_rwfa_is_always_eu_uk_ok(self):
        # The board is fully-remote worldwide by policy - any category.
        self.assertEqual(job_alert.geo_from_location(None, "fullstack"),
                         job_alert.GEO_OK)
        self.assertEqual(job_alert.geo_from_location(None, "customer-support"),
                         job_alert.GEO_OK)

    def test_moai_location_signals(self):
        f = job_alert.geo_from_location
        self.assertEqual(f("World Wide - Remote", "moaijobs"),
                         job_alert.GEO_OK)
        self.assertEqual(f("Lisbon, Portugal", "moaijobs"), job_alert.GEO_OK)
        self.assertEqual(f("London, UK", "moaijobs"), job_alert.GEO_OK)
        self.assertEqual(f("Toronto, Canada", "moaijobs"), job_alert.GEO_OK)
        self.assertEqual(f("REMOTE- US", "moaijobs"), job_alert.GEO_US_ONLY)
        self.assertEqual(f("Mountain View, California, United States",
                           "moaijobs"), job_alert.GEO_US_ONLY)
        self.assertEqual(f("Remote within the United States", "moaijobs"),
                         job_alert.GEO_US_ONLY)
        self.assertEqual(f("Austin, TX, US", "moaijobs"), job_alert.GEO_US_ONLY)
        self.assertIsNone(f(None, "moaijobs"))
        self.assertIsNone(f("", "moaijobs"))

    def test_remote_with_parens_or_slash_counts_as_us_only(self):
        # "Remote (US/Canada)" (Censys) must read as US-only: the separator
        # between "remote" and the country code can carry parentheses and
        # slashes, not only spaces and dashes.
        f = job_alert.geo_from_location
        self.assertEqual(f("Remote (US/Canada)", "moaijobs"),
                         job_alert.GEO_US_ONLY)
        self.assertEqual(f("Remote/US", "moaijobs"), job_alert.GEO_US_ONLY)
        self.assertEqual(f("US (Remote)", "moaijobs"), job_alert.GEO_US_ONLY)
        self.assertEqual(f("World Wide - Remote", "moaijobs"),
                         job_alert.GEO_OK)

    MOAI_RSS_LOC = (
        '<?xml version="1.0"?><rss><channel>'
        "<item>"
        "<title><![CDATA[LLM Engineer at Acme]]></title>"
        "<link><![CDATA[https://www.moaijobs.com/job/llm-engineer-acme-9]]></link>"
        "<pubDate>Sat, 05 Sep 2026 10:00:00 GMT</pubDate>"
        "<description><![CDATA[&lt;p&gt;&lt;strong&gt;Location:&lt;/strong&gt; "
        "Mountain View, California, United States&lt;/p&gt;"
        "&lt;p&gt;&lt;strong&gt;Salary:&lt;/strong&gt; $100k - $150k&lt;/p&gt;"
        "]]></description>"
        "</item>"
        "<item>"
        "<title><![CDATA[ML Engineer at GlobeCorp]]></title>"
        "<link><![CDATA[https://www.moaijobs.com/job/ml-engineer-globecorp-10]]></link>"
        "<pubDate>Sat, 05 Sep 2026 09:00:00 GMT</pubDate>"
        "<description><![CDATA[<p><strong>Location:</strong> "
        "World Wide - Remote</p><p><strong>Skills:</strong> python, llm</p>"
        "]]></description>"
        "</item>"
        "</channel></rss>"
    )

    def test_moai_rss_extracts_location_and_geo_both_escapings(self):
        cards = job_alert.parse_moai_rss(self.MOAI_RSS_LOC)
        self.assertEqual(cards[0]["location"],
                         "Mountain View, California, United States")
        self.assertEqual(cards[0]["geo"], job_alert.GEO_US_ONLY)
        # The second item's description is raw (not double-escaped) HTML.
        self.assertEqual(cards[1]["location"], "World Wide - Remote")
        self.assertEqual(cards[1]["geo"], job_alert.GEO_OK)

    def test_moai_item_without_location_field_is_untagged(self):
        # The shared MOAI_RSS fixture's description has no Location field.
        cards = job_alert.parse_moai_rss(MOAI_RSS)
        self.assertIsNone(cards[0]["location"])
        self.assertIsNone(cards[0]["geo"])

    def test_rwfa_cards_are_tagged_ok_at_parse_time(self):
        cards = job_alert.parse_cards(CARD, "product")
        self.assertIsNone(cards[0]["location"])
        self.assertEqual(cards[0]["geo"], job_alert.GEO_OK)

    def test_render_section_shows_geo_tag(self):
        card = job_alert.parse_cards(CARD, "product")[0]
        card["geo"] = job_alert.GEO_OK
        self.assertIn("🌍 EU/UK ok", job_alert.render_section([card])[0])
        card["geo"] = job_alert.GEO_US_ONLY
        self.assertIn("🇺🇸 US-only", job_alert.render_section([card])[0])
        card["geo"] = None
        rendered = job_alert.render_section([card])[0]
        self.assertNotIn("🌍", rendered)
        self.assertNotIn("🇺🇸", rendered)

    def test_render_comment_summary_line(self):
        cards = job_alert.parse_cards(CARD, "product")
        body = job_alert.render_comment(
            "http://run", "d", cards, [], [], bootstrapped=False,
            summary="**Tag summary**")
        self.assertIn("> **Tag summary**", body)
        self.assertIn("🌍 EU/UK ok", body)

    def test_daily_footer_documents_the_tags(self):
        body = job_alert.render_comment("http://run", "d", [], [], [],
                                        bootstrapped=False)
        self.assertIn("tags: 🌍 EU/UK ok / 🇺🇸 US-only", body)

    def test_bootstrap_note_documents_the_tags(self):
        body = job_alert.render_comment("http://run", "d", [], [], [],
                                        bootstrapped=True)
        self.assertIn("location tag", body)


class RunWeeklyWiringTests(unittest.TestCase):
    """_run_weekly's orchestration, mocked at the REST boundary: issue
    lookup, comment fetch, summary render, post - and the quiet no-issue
    path. main() must route --weekly into _run_weekly."""

    def _run(self, extra, monkey_issues, monkey_comments, monkey_posts):
        argv = ["--weekly", *extra]
        job_alert.find_issue = lambda force=None: monkey_issues(force)
        job_alert.fetch_comments = lambda issue: monkey_comments(issue)
        job_alert.post_comment = lambda issue, body: monkey_posts(issue, body)
        return job_alert.main(argv)

    def test_weekly_dry_run_touches_nothing(self):
        posts = []
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            code = self._run(
                ["--dry-run"],
                lambda force: 7,
                lambda issue: [{"id": 1, "created": "2026-09-05T07:05:00Z",
                                "body": "<!-- weekly-counts aGVsbG8=-->"}],
                lambda issue, body: posts.append((issue, body)))
        self.assertEqual(code, 0)
        self.assertEqual(posts, [])  # dry run must not comment

    def test_weekly_posts_summary_to_the_issue(self):
        posts = []
        code = self._run(
            [],
            lambda force: 7,
            lambda issue: [],
            lambda issue, body: posts.append((issue, body)))
        self.assertEqual(code, 0)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][0], 7)
        self.assertIn("Weekly trend", posts[0][1])

    def test_weekly_without_issue_is_quiet_success(self):
        posts = []
        code = self._run(
            [], lambda force: None, lambda issue: (_ for _ in ()).throw(
                AssertionError("must not fetch comments")),
            lambda issue, body: posts.append((issue, body)))
        self.assertEqual(code, 0)
        self.assertEqual(posts, [])

    def test_main_routes_weekly_flag(self):
        called = []
        original = job_alert._run_weekly
        job_alert._run_weekly = lambda args: called.append(args) or 5
        try:
            self.assertEqual(job_alert.main(["--weekly"]), 5)
        finally:
            job_alert._run_weekly = original
        self.assertEqual(len(called), 1)
        self.assertTrue(called[0].weekly)


class WeeklyWorkflowWiringTests(unittest.TestCase):
    def test_sunday_cron_and_mode_wiring(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('cron: "20 7 * * 0"', text)
        self.assertIn("--weekly", text)
        self.assertIn("IS_SUNDAY: ${{ github.event.schedule == '20 7 * * 0' }}", text)
        self.assertIn("MODE: ${{ inputs.mode || 'daily' }}", text)
        self.assertIn("- weekly", text)  # workflow_dispatch choice


if __name__ == "__main__":
    unittest.main()
