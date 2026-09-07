# Real Work From Anywhere URL Reference

Public, unauthenticated pages used by this skill. `robots.txt` allows all paths
(`User-Agent: * / Allow: /`); there is no public JSON API and no server-side
search.

## Listing pages (scraped categories)

Each category is **one complete HTML page** — no pagination, no query parameters:

```
GET https://www.realworkfromanywhere.com/remote-fullstack-jobs
GET https://www.realworkfromanywhere.com/remote-backend-jobs
GET https://www.realworkfromanywhere.com/remote-software-developer-jobs
GET https://www.realworkfromanywhere.com/remote-product-jobs
GET https://www.realworkfromanywhere.com/remote-design-jobs
GET https://www.realworkfromanywhere.com/remote-sales-and-marketing-jobs
GET https://www.realworkfromanywhere.com/remote-customer-support-jobs
```

The portal also exposes categories this skill does not fetch
(`management-and-finance`, `devops-and-sysadmin`, `frontend`, `fullstack` —
only the latter is fetched); their slugs follow the same `remote-<name>-jobs`
pattern. DevOps and frontend are not fetched because the fullstack, backend,
and software-developer pages already cover most of their overlap.

Each page has a heading of the form `Found N remote <category> jobs` (the total
count, as a sanity anchor) and then one job card per listing:

## Job card markup (listing pages)

Cards split cleanly on `<a href="/jobs/<slug>-<id>" class="block w-full rounded-lg…">`.
Per-card anchors:

| Field | Anchor |
|-------|--------|
| id | trailing digits of the slug: `/jobs/<slug>-<id>` |
| url | the card anchor's `href`, prefixed `https://www.realworkfromanywhere.com` |
| title | the card's only `<h3>` |
| company | `<p class="text-base truncate font-medium …">` directly after the title |
| date | relative text (`"New"`, `"1 day ago"`, `"2 weeks ago"`, `"3 months ago"`) in `<span class="hidden md:block …">` (desktop) or `<span class="md:hidden …">` (mobile duplicate) |
| location | `<span class="truncate"><span>…</span></span>` inside the globe-icon row; currently always `"Anywhere in the World"` |
| salary | optional `<span class="whitespace-nowrap">$… USD</span>` |
| tags | repeated `<span class="badge …">skill</span>` |

A `"Featured"` ribbon exists in the portal's ad slots but no card in these four
categories carried it at build time; if ads start appearing inside the card
flow, re-check card-class discrimination here.

## Detail page

```
GET https://www.realworkfromanywhere.com/jobs/<slug>-<id>
```

The page embeds a schema.org block at `<script type="application/ld+json">` with
`JobPosting` fields: `title`, `description` (HTML — strip tags, keep `<br>`/block
breaks), `datePosted` (ISO), `validThrough` (application deadline), `employmentType`,
`jobLocationType` (`TELECOMMUTE`), and `hiringOrganization.name` (company). It also
has `<link rel="canonical">` with the job's own URL.

The **external apply link** (company ATS: Pinpoint, Greenhouse, Lever, …) is the
`<a href="https://…" rel="nofollow noopener" target="_blank"><button … bg-purple-500>` at the
end of the posting article.

## Id resolution (detail by numeric id)

Detail URLs require the full slug, so a bare id needs one lookup:

```
GET https://www.realworkfromanywhere.com/sitemap.xml
```

A flat `<urlset>` of `<loc>` entries (jobs have `priority 0.9`, `changefreq daily`,
and a `lastmod` timestamp). The CLI matches the entry whose slug ends in `-<id>`;
the hyphen guard prevents `7580` from matching `17580`.

## Quirks

- No server-side search and no `/api/*` JSON endpoints (verified by probing;
  all 404). Category RSS feeds exist at `<category>/rss.xml` and carry full
  descriptions but **no company names**, so HTML is the primary source.
- The root `/rss.xml` path returns the portal's HTML 404 page (not a feed).
- Pagination (`/page/2`…`/page/21`) exists on the homepage only and mixes all
  categories; it is unused by this skill because the category pages are complete.
- The relative dates on cards round hours/minutes up to "1 day ago"; for exact
  posting times use the detail page's `datePosted`.
