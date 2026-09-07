---
name: moaijobs-search
version: 1.0.0
description: >
  Use this skill to search MoAIJobs (moaijobs.com), a curated board of
  AI-native jobs at AI companies and AI-hiring teams. Invoke for AI engineer,
  ML engineer, research engineer/scientist, data science, and AI agent
  openings, LLM and RAG roles, and remote AI positions. Trigger phrases:
  AI jobs, machine learning engineer jobs, LLM roles, research engineer
  positions, AI agent jobs, data science openings, vagas de IA, vagas de
  machine learning, empregos de inteligência artificial.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/moaijobs-search/cli/src/cli.ts *)
---

# MoAIJobs Search Skill

Search live AI job listings from MoAIJobs' public board. No authentication,
no API key, **zero runtime dependencies** — it runs with just `bun`.

## When to use this skill

- Find AI/ML/research/data-science/AI-agent openings on a curated AI-only board
- Filter by category (7 profile-relevant categories are wired in), recency (`--jobage`), or keywords
- Get the full description, deadline, salary, and external apply link of a specific posting

## How it works (read before relying on category filters)

The portal has **no server-side search and no JSON API**. The complete board
(~290+ postings) is published in **one RSS feed** (`/ai-jobs.rss`), which the
CLI fetches and filters client-side — so a plain `search -q` always sees the
whole board. Category pages (`/ai-engineer-jobs`, …) serve **at most the 90
most recent postings each** and are fetched only for `--category` filtering;
a category filter can therefore hide older matches that a plain search sees.

Categories wired in (chosen for this workspace's applied-AI/research profile):
`ai-engineer`, `ml-engineer`, `research-engineer`, `research-scientist`,
`data-science`, `ai-agents`, `remote-ai`. The portal also has
`generative-ai-jobs`, `ai-training-jobs`, `robotics-jobs`, and
`ai-internship-jobs` — add a line to `CATEGORY_PATHS` in `cli/src/helpers.ts`
to include them.

## Commands

### Search job listings

```bash
bun run .agents/skills/moaijobs-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keywords matched client-side against title, company, location, and salary. Optional: without it you get the whole board.
- `--category <name>` / `-c <name>` — restrict to one category (repeatable, comma-separated accepted). See the caveat above.
- `--jobage <days>` — posted within N days (relative card dates; unparseable dates are kept, never silently dropped).
- `--page <n>` / `--limit <n>` / `-n <n>` — client-side slicing of results.
- `--format json|table|plain` — default `json`.

There is no `--location` flag: locations live in the results, filter client-side or include the place in `--query`.

### Fetch full job detail

```bash
bun run .agents/skills/moaijobs-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

`id` is the numeric id from `search` results (e.g. `6034`); a full
`moaijobs.com/job/...` URL also works. Detail pages embed schema.org
`JobPosting` JSON-LD — the CLI returns description, posted date, deadline
(`validThrough`), employment type, salary, and the external apply link
(Greenhouse/Lever/etc.). Bare ids are resolved through the RSS feed (the
sitemap lists only category pages).

## Usage examples

```bash
# LLM roles across the whole board
bun run .agents/skills/moaijobs-search/cli/src/cli.ts search -q "LLM" --format table

# Research engineer roles posted in the last 14 days
bun run .agents/skills/moaijobs-search/cli/src/cli.ts search -q "research engineer" --jobage 14 --format table

# AI agent openings only
bun run .agents/skills/moaijobs-search/cli/src/cli.ts search -c ai-agents --format table

# Two categories at once
bun run .agents/skills/moaijobs-search/cli/src/cli.ts search -q "engineer" -c ai-engineer -c remote-ai --format table

# Full details for a specific posting
bun run .agents/skills/moaijobs-search/cli/src/cli.ts detail 6034 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing ids to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors go to **stderr** as `{ "error": "...", "code": "..." }` and the
process exits `1` (`BAD_CATEGORY`, `UNKNOWN_FLAG`, `FEED_UNAVAILABLE`,
`BAD_ID`, …). Unknown flags are never silently ignored — a discarded filter
would change results without telling you.

## Notes

- Public pages and public RSS only; `robots.txt` allows all paths; no credentials or bot protection. Keep request volume low — one RSS request per search, category pages only when filtering.
- The feed is ~2.8 MB; search results deliberately omit description bodies to stay lean.
- If the board parses to zero postings the CLI errors out (`FEED_EMPTY`) instead of returning silence — markup changes surface as visible failures. Parsing anchors are documented in `url-reference.md`.
