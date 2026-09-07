---
name: realworkfromanywhere-search
version: 1.0.0
description: >
  Use this skill to search Real Work From Anywhere (realworkfromanywhere.com),
  a curated board of fully-remote, work-from-anywhere jobs at verified
  worldwide companies — every listing is remote globally, no exceptions.
  Invoke for worldwide remote openings, digital-nomad-friendly roles, and
  location-flexible positions in software development, backend, fullstack,
  customer support, design, product, and more. Trigger phrases: work from
  anywhere jobs, fully remote jobs worldwide, remote jobs anywhere, remote
  developer jobs, vagas remotas internacionais, emprego remoto worldwide,
  "remote job in <field>", realworkfromanywhere.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/realworkfromanywhere-search/cli/src/cli.ts *)
---

# Real Work From Anywhere Search Skill

Search live listings from **Real Work From Anywhere** (realworkfromanywhere.com) —
a curated board where every posting is fully remote worldwide ("Anywhere in the
World", no location restrictions). No authentication, no API key, and **zero
runtime dependencies** — it runs with just `bun`.

The portal publishes one **complete listing page per category** (no pagination,
no server-side keyword search). This CLI fetches the category pages, merges them,
and filters by keyword client-side. Scraped categories: fullstack, backend,
software developer, product, design, sales & marketing, and customer support.

## When to use this skill

- Find fully-remote, work-from-anywhere roles by keyword (title, skill, salary)
- Filter by posting recency (`--jobage`) or restrict to a category (`--category`)
- Get a posting's full description, deadline, employment type, and external apply link

## Commands

### Search listings

```bash
bun run .agents/skills/realworkfromanywhere-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keyword filter (title, company, skill badge,
  salary). Optional: omit it to list everything on the category pages. Multi-word
  queries AND their terms ("software engineer" matches "Senior Software Engineer").
- `--category <name>` / `-c <name>` — restrict to one category; repeatable.
  Categories: `fullstack`, `backend`, `software-developer`, `product`, `design`,
  `sales-and-marketing`, `customer-support`.
- `--jobage <days>` — posted within N days (parsed from the card's relative date).
- `--page <n>` — 1-indexed page of results (client-side slicing).
- `--limit <n>` / `-n <n>` — cap total results emitted (client-side).
- `--format json|table|plain` — default `json`.

There is **no `--location` flag**: every listing on the portal is remote worldwide.

### Fetch full job detail

```bash
bun run .agents/skills/realworkfromanywhere-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

`id` is the numeric id from `search` results (e.g. `7580`). A full
`realworkfromanywhere.com/jobs/...` URL also works. Returns the full description,
application deadline, employment type, and the external apply link (the company's
own ATS, e.g. Greenhouse/Lever/Pinpoint).

## Usage examples

```bash
# All developer-ish roles across the scraped categories
bun run .agents/skills/realworkfromanywhere-search/cli/src/cli.ts search -q "developer" --format table

# Backend roles mentioning postgres, last 14 days
bun run .agents/skills/realworkfromanywhere-search/cli/src/cli.ts search -q "postgres" -c backend --jobage 14 --format table

# Everything on the customer-support category page
bun run .agents/skills/realworkfromanywhere-search/cli/src/cli.ts search -c customer-support --format table

# Search salaries
bun run .agents/skills/realworkfromanywhere-search/cli/src/cli.ts search -q "140,000" --format table

# Full details for one posting
bun run .agents/skills/realworkfromanywhere-search/cli/src/cli.ts detail 7580 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing IDs to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the
process exits with code `1`.

## Notes

- Data is from the portal's public category pages — no credentials required;
  robots.txt permits access and no personal-use warning is needed.
- There is no server-side search: keyword filtering happens client-side over
  titles, companies, skill badges, and salaries. A niche term that only appears
  in the description body will not match — open the posting's `detail` to check.
- Scope: the seven categories above cover everything but `management-and-finance`;
  extend `CATEGORY_PATHS` in `cli/src/helpers.ts` to include it or any new
  category the portal adds.
- Posting dates on cards are relative ("2 days ago", "New"); the detail page
  exposes the absolute `datePosted` and `validThrough` deadline via JSON-LD.
- The portal may rate-limit; the CLI retries 429/5xx with exponential backoff.
  Keep volume low anyway — it's a small curated board.
- If the portal changes its markup, the parsing anchors are recorded in
  `url-reference.md`.
