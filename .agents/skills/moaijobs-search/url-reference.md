# MoAIJobs URL Reference

Data source notes for moaijobs.com, recorded so future markup changes can be
diagnosed without re-doing the recon. Recon date: 2026-09-06.

## Base URL

```
https://www.moaijobs.com
```

## Access

- `robots.txt` allows all paths; no login, no bot protection, no paid fetcher.
- **No server-side search endpoint** (probed `/search?q=`, `/jobs?q=`, `/?q=` — none exist) and **no JSON API**.
- Homepage links ~19 pages; job detail URLs are `/job/<slug>-<id>`.

## The RSS feed is the board

```
https://www.moaijobs.com/ai-jobs.rss
```

- One request returns the **complete board** (~290+ items, ~2.8 MB).
- Item shape: `<title>` ("Role at Company"), `<link>` (`/job/<slug>-<id>`),
  `<pubDate>` (RFC-822), `<description>` (HTML). **No** `<guid>`, **no**
  `<category>` elements — category is only visible on category pages.
- The description is **double-escaped**: a CDATA block whose body is itself
  entity-escaped HTML (`&lt;p&gt;…`). Decode entities twice before stripping tags.
- The description header carries the identity block:
  `<p><strong>Company:</strong> …</p><p><strong>Location:</strong> …</p>` —
  the CLI reads Location from here.
- Titles split on the **last** `" at "` so roles containing `" at "` survive
  (e.g. "Engineer at Scale at Cohere" → title "Engineer at Scale", company "Cohere").

## Category pages

```
https://www.moaijobs.com/{category}-jobs
```

All categories (from `/sitemap.xml`, which lists **only** category pages —
no `/job/` URLs):

| Category page | In CLI? |
|---------------|---------|
| `/ai-engineer-jobs` | yes |
| `/ml-engineer-jobs` | yes |
| `/research-engineer-jobs` | yes |
| `/research-scientist-jobs` | yes |
| `/data-science-jobs` | yes |
| `/ai-agents-jobs` | yes |
| `/remote-ai-jobs` | yes |
| `/generative-ai-jobs` | no (add to `CATEGORY_PATHS` if wanted) |
| `/ai-training-jobs` | no |
| `/robotics-jobs` | no |
| `/ai-internship-jobs` | no |

- Each serves **at most the 90 most recent postings** of that category, no
  pagination: `?page=2` returns the same cards as page 1 (verified live).
  A category filter can therefore hide older board matches.
- Card anchor: `<a href="/job/<slug>-<id>" aria-label="View job details">` (shadcn `data-slot="card"` markup).
  - Title: `<h3 class="truncate text-xl font-semibold">…</h3>`
  - Company: `<p class="text-muted-foreground truncate text-base">…</p>`
  - Date: `<span class="text-muted-foreground ml-auto …">3 days ago</span>` (relative; "New" = today)
  - Badges: `<span data-slot="badge" class="font-normal">…</span>` repeated —
    first badge starting with `$` (or containing "an hour") is the salary, the
    first non-salary badge is the primary location, extras are alternate offices.

## Job detail page

```
https://www.moaijobs.com/job/<slug>-<id>
```

- Embeds one `<script type="application/ld+json">` schema.org `JobPosting`:
  `title`, `description`, `datePosted`, `validThrough` (deadline),
  `employmentType`, `hiringOrganization.name`, `jobLocation[].address`,
  `baseSalary{currency, value{minValue, maxValue, unitText}}`.
- Apply link: the only **external** anchor with `role="button"`
  (`rel="noopener nofollow"`), e.g. `https://job-boards.greenhouse.io/…`.
  Company-careers and social links are plain anchors without `role`.
- Canonical URL: `<link rel="canonical" href="…">`.

## Id → URL resolution

Detail URLs require the full slug, and the sitemap does not list `/job/` URLs,
so a bare numeric id is resolved by scanning the RSS feed's `<link>` entries
for one ending in `-{id}`. The feed is the complete id index.

## If parsing breaks

Update, in `cli/src/helpers.ts`: the RSS item split (`<item>`), the
`<strong>Location:</strong>` header regex, the card anchor split
(`<a href="/job/`), the badge regex (`font-normal">…</span>`), the JSON-LD
script tag, and the `role="button"` apply-link regex. A board that parses to
zero postings fails loudly (`FEED_EMPTY`) by design.
