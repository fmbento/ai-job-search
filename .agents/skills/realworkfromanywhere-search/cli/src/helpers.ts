// Data source: Real Work From Anywhere (realworkfromanywhere.com) public pages.
// No authentication required. robots.txt allows all paths.
//
// The site has no server-side keyword search and no public JSON API. It serves
// one complete, unpaginated HTML page per job category; this CLI fetches the
// relevant category pages in parallel, parses their job cards, merges and
// dedupes them, then filters client-side. Detail comes from each job page's
// embedded schema.org JobPosting JSON-LD.
//
// Parsing is chunked regex by design (see add-portal.md's portal-skill
// contract): the markup is shallow and stable, one malformed card cannot break
// the rest, and zero runtime dependencies keeps `bun install` clean.

export const BASE_URL = "https://www.realworkfromanywhere.com"

/**
 * Category pages to fetch for a search. Each page is a complete listing for
 * that category (no pagination); "-" inside the path is the portal's own slug.
 */
export const CATEGORY_PATHS = {
  fullstack: "/remote-fullstack-jobs",
  backend: "/remote-backend-jobs",
  "software-developer": "/remote-software-developer-jobs",
  product: "/remote-product-jobs",
  design: "/remote-design-jobs",
  "sales-and-marketing": "/remote-sales-and-marketing-jobs",
  "customer-support": "/remote-customer-support-jobs",
} as const

export type CategorySlug = keyof typeof CATEGORY_PATHS

export const CATEGORY_SLUGS = Object.keys(CATEGORY_PATHS) as CategorySlug[]

/** Categories to fetch when the user gives none. */
export const DEFAULT_CATEGORIES: CategorySlug[] = [
  "fullstack",
  "backend",
  "software-developer",
  "product",
  "design",
  "sales-and-marketing",
  "customer-support",
]

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; realworkfromanywhere-cli/1.0)"

/** Fetch with exponential backoff + jitter on 429/5xx. Returns "" on a 404. */
export async function htmlFetch(url: string): Promise<string> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: {
        "User-Agent": UA,
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
      redirect: "follow",
      signal: AbortSignal.timeout(15000),
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      }
      const jitter = Math.floor(Math.random() * 500)
      await new Promise((r) => setTimeout(r, delay + jitter))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (response.status === 404) return ""
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    }
    return response.text()
  }
  throw new Error("Request failed after max retries")
}

export interface JobCard {
  id: string
  title: string
  company: string | null
  companyUrl: string | null
  location: string | null
  date: string | null
  url: string
  category: string
  salary: string | null
  tags: string[]
}

export interface JobDetail extends JobCard {
  description: string | null
  deadline: string | null
  employmentType: string | null
  applyUrl: string | null
}

/**
 * Convert a Unicode code point to a string. Uses `fromCodePoint` (not
 * `fromCharCode`) so supplementary-plane code points (e.g. emoji, U+1F600)
 * decode correctly, and drops out-of-range values instead of throwing.
 */
function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    // Numeric character references: decimal (&#233;) and hexadecimal (&#xE9;).
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    .replace(/&nbsp;/g, " ")
}

function stripTags(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()
}

function clean(html: string): string {
  return decodeHtmlEntities(stripTags(html))
}

/**
 * Parse one category page into job cards. The page splits cleanly on each
 * card's opening anchor (`<a href="/jobs/<slug>-<id>" class="block w-full
 * rounded-lg…"`), so each chunk is parsed independently and one malformed card
 * cannot break the rest. Headings/nav job links outside cards are excluded by
 * the card-class match on the chunk's own anchor tag.
 */
export function parseJobCards(html: string, category: string): JobCard[] {
  const results: JobCard[] = []
  const chunks = html.split('<a href="/jobs/').slice(1)

  for (const chunk of chunks) {
    const urlMatch = chunk.match(/^([a-z0-9-]+)" class="block w-full rounded-lg/)
    if (!urlMatch) continue
    const slug = urlMatch[1]

    // The numeric id is the trailing segment of the slug.
    const idMatch = slug.match(/-(\d+)$/)
    if (!idMatch) continue
    const id = idMatch[1]

    // Title: the card's only <h3>.
    const titleMatch = chunk.match(/<h3[^>]*>([\s\S]*?)<\/h3>/i)
    const title = titleMatch ? clean(titleMatch[1]) : null
    if (!title) continue

    // Company: the <p> immediately after the title's parent div, marked by
    // its "truncate" utility class.
    const companyMatch = chunk.match(
      /<p class="text-base truncate font-medium[^"]*">([\s\S]*?)<\/p>/i,
    )
    const company = companyMatch ? clean(companyMatch[1]) || null : null

    // Relative posting date ("1 day ago", "New"); rendered twice (mobile +
    // desktop spans). Prefer the desktop variant, fall back to the first.
    const dateDesktop = chunk.match(
      /class="hidden md:block[^"]*text-base-content\/80"*>([\s\S]*?)<\/span>/i,
    )
    const dateAny = chunk.match(/text-base-content\/80"*>([\s\S]*?)<\/span>/i)
    const dateText = (dateDesktop ?? dateAny)?.[1]
    const date = dateText ? clean(dateText) || null : null

    // Location: a span inside the pin-globe icon row. All current listings
    // read "Anywhere in the World"; matched by the wrapping span, not the text.
    const locMatch = chunk.match(
      /class="truncate"><span>([\s\S]*?)<\/span><\/span>/i,
    )
    const location = locMatch ? clean(locMatch[1]) || null : null

    // Salary: whitespace-nowrap span after the salary icon; absent when the
    // posting lists no range.
    const salaryMatch = chunk.match(/<span class="whitespace-nowrap">(\$[\s\S]*?)<\/span>/i)
    const salary = salaryMatch ? clean(salaryMatch[1]) || null : null

    // Skill badges: spans with class "badge", e.g. postgres, kubernetes.
    const tags: string[] = []
    const badgeRe = /<span class="badge[^"]*">([\s\S]*?)<\/span>/gi
    let bm: RegExpExecArray | null
    while ((bm = badgeRe.exec(chunk)) !== null) {
      const tag = clean(bm[1])
      if (tag) tags.push(tag)
    }

    results.push({
      id,
      title,
      company,
      companyUrl: null,
      location,
      date,
      url: `${BASE_URL}/jobs/${slug}`,
      category,
      salary,
      tags,
    })
  }

  return results
}

/** Client-side keyword filter over title, company, tags, and salary. */
export function matchesQuery(card: JobCard, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  // Split into terms so "software engineer" matches "Senior Software
  // Engineer - Ledger" even when the exact phrase does not appear.
  const terms = q.split(/\s+/).filter(Boolean)
  const haystack = [card.title, card.company ?? "", card.salary ?? "", ...card.tags]
    .join(" ")
    .toLowerCase()
  return terms.every((t) => haystack.includes(t))
}

/**
 * Posting age in days from the card's relative date text ("New", "1 day ago",
 * "2 weeks ago", "3 months ago"). Returns null for unparseable text — a card
 * whose date cannot be read must not be silently dropped by --jobage.
 */
export function relativeDateToDays(text: string | null): number | null {
  if (!text) return null
  const t = text.trim().toLowerCase()
  if (t === "new") return 0
  const m = t.match(/^(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago$/)
  if (!m) return null
  const n = parseInt(m[1], 10)
  switch (m[2]) {
    case "second":
      return 0
    case "minute":
      return 0
    case "hour":
      return 0
    case "day":
      return n
    case "week":
      return n * 7
    case "month":
      return n * 30
    default:
      return null
  }
}

/**
 * Parse a job detail page. The page embeds a schema.org JobPosting JSON-LD
 * block with the authoritative fields; the external apply link (Greenhouse,
 * Lever, Pinpoint, …) lives on the purple button after the description.
 */
export function parseJobDetail(html: string, id: string): JobDetail {
  // JSON-LD block.
  const ldStart = html.indexOf('<script type="application/ld+json">')
  let title: string | null = null
  let company: string | null = null
  let description: string | null = null
  let datePosted: string | null = null
  let deadline: string | null = null
  let employmentType: string | null = null

  if (ldStart !== -1) {
    const ldEnd = html.indexOf("</script>", ldStart)
    if (ldEnd !== -1) {
      const raw = html.slice(ldStart + '<script type="application/ld+json">'.length, ldEnd)
      try {
        const ld = JSON.parse(raw) as {
          title?: string
          description?: string
          datePosted?: string
          validThrough?: string
          employmentType?: string
          hiringOrganization?: { name?: string }
        }
        title = ld.title ?? null
        company = ld.hiringOrganization?.name ?? null
        datePosted = ld.datePosted ?? null
        deadline = ld.validThrough ?? null
        employmentType = ld.employmentType ?? null
        if (ld.description) {
          const withBreaks = ld.description
            .replace(/<\s*br\s*\/?>/gi, "\n")
            .replace(/<\/(p|li|ul|ol|div|h\d)>/gi, "\n")
          // Strip the remaining tags and decode entities while preserving the
          // newlines above: the shared stripTags() collapses ALL whitespace
          // runs, which would flatten the posting's paragraph structure.
          description =
            decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, ""))
              .replace(/[^\S\n]+/g, " ")
              .replace(/ ?\n ?/g, "\n")
              .replace(/\n{3,}/g, "\n\n")
              .trim() || null
        }
      } catch {
        // Malformed JSON-LD falls through to card-style parsing below.
      }
    }
  }

  // Card-style fallbacks when JSON-LD is missing or malformed.
  if (!title) {
    const h1 = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)
    title = h1 ? clean(h1[1]) : null
  }
  if (!datePosted) {
    const rel = html.match(/Posted\s*(?:<!-- -->)?\s*([^<]+?)<\/p>/i)
    if (rel) datePosted = clean(rel[1]) || null
  }

  // External apply link: the button inside the mt-auto block after the article.
  const applyMatch = html.match(
    /<a href="(https?:\/\/[^"]+)" rel="nofollow noopener" target="_blank"><button[^>]*bg-purple-500/i,
  )
  const applyUrl = applyMatch ? decodeHtmlEntities(applyMatch[1]) : null

  // Page's own URL: the slug anchor appears in the breadcrumbs only for the
  // job's own link is not present; reconstruct from the canonical link tag.
  const canonical = html.match(/<link rel="canonical" href="([^"]+)"/i)
  const url = canonical
    ? decodeHtmlEntities(canonical[1])
    : `${BASE_URL}/jobs/unknown-${id}`

  return {
    id,
    title: title || "(untitled)",
    company,
    companyUrl: null,
    location: "Anywhere in the World",
    date: datePosted,
    url,
    category: "detail",
    salary: null,
    tags: [],
    description,
    deadline,
    employmentType,
    applyUrl,
  }
}

/**
 * Resolve a job id (or any /jobs/ URL) to its canonical slug URL using the
 * portal's sitemap. Detail URLs include the full slug, so a bare numeric id
 * needs this lookup. Returns null when the id is not in the sitemap.
 */
export async function resolveJobUrl(idOrUrl: string): Promise<string | null> {
  if (/^https?:\/\//.test(idOrUrl)) {
    if (idOrUrl.includes("/jobs/")) return idOrUrl.split("#")[0]
  }
  const bare = idOrUrl.match(/^(\d+)$/)
  if (!bare) return null
  const id = bare[1]
  const xml = await htmlFetch(`${BASE_URL}/sitemap.xml`)
  if (!xml) return null
  // Split per <url> block so one malformed entry cannot break the scan.
  const blocks = xml.split(/<url>/).slice(1)
  // "-7580" requires a hyphen directly before the digits, so a slug ending in
  // e.g. -17580 cannot match an id of 7580.
  const pattern = new RegExp(`<loc>[^<]*/jobs/([a-z0-9-]*-${id})</loc>`)
  for (const block of blocks) {
    if (!block.includes(`<loc>${BASE_URL}/jobs/`)) continue
    const m = block.match(pattern)
    if (m) return `${BASE_URL}/jobs/${m[1]}`
  }
  return null
}
