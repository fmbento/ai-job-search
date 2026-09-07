// Data source: MoAIJobs (moaijobs.com) public pages and RSS feed.
// No authentication required. robots.txt allows all paths.
//
// The site has no server-side keyword search and no JSON API. The complete
// board (~293 postings) is published in one RSS feed, /ai-jobs.rss, whose
// items carry title ("Role at Company"), link (/job/<slug>-<id>), pubDate,
// and an HTML description with a Company/Location header. Category pages
// (/ai-engineer-jobs etc.) serve at most the 90 most recent cards per
// category and are the only place a posting's category is visible.
//
// Strategy: the RSS feed is the primary dataset (complete, one request);
// category pages supply the per-posting category and are fetched only when
// the user filters by category. Search results stay lean (no description
// bodies - the feed alone is 2.8 MB); `detail` fetches the posting page and
// reads its schema.org JobPosting JSON-LD.
//
// Parsing is chunked regex by design (see add-portal.md's portal-skill
// contract): the markup is shallow and stable, one malformed card cannot
// break the rest, and zero runtime dependencies keeps `bun install` clean.

export const BASE_URL = "https://www.moaijobs.com"
export const RSS_PATH = "/ai-jobs.rss"

/**
 * Category pages. Each serves at most the 90 most recent postings for that
 * category (no pagination - ?page=2 returns the same cards; verified live).
 * Chosen for the workspace profile: applied AI / research engineering /
 * ML / data science / agents, plus the remote-ai cross-cut. The portal also
 * has generative-ai-jobs, ai-training-jobs, robotics-jobs, and
 * ai-internship-jobs; extend this map to include them.
 */
export const CATEGORY_PATHS = {
  "ai-engineer": "/ai-engineer-jobs",
  "ml-engineer": "/ml-engineer-jobs",
  "research-engineer": "/research-engineer-jobs",
  "research-scientist": "/research-scientist-jobs",
  "data-science": "/data-science-jobs",
  "ai-agents": "/ai-agents-jobs",
  "remote-ai": "/remote-ai-jobs",
} as const

export type CategorySlug = keyof typeof CATEGORY_PATHS

export const CATEGORY_SLUGS = Object.keys(CATEGORY_PATHS) as CategorySlug[]

/** Categories fetched for a --category filter; empty means RSS-only. */
export function categoriesFor(names: string[]): CategorySlug[] {
  return names as CategorySlug[]
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; moaijobs-cli/1.0)"

/** Fetch with exponential backoff + jitter on 429/5xx. Returns "" on a 404. */
export async function htmlFetch(url: string): Promise<string> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: {
        "User-Agent": UA,
        Accept: "text/html,application/xhtml+xml,application/xml,application/rss+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
      redirect: "follow",
      signal: AbortSignal.timeout(20000),
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
  category: string | null
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
 * The portal double-escapes description bodies (a CDATA block holding
 * entity-escaped HTML), so decode twice before stripping tags.
 */
function cleanDeep(html: string): string {
  return decodeHtmlEntities(decodeHtmlEntities(stripTags(html)))
}

function cdata(inner: string): string {
  const m = inner.match(/<!\[CDATA\[([\s\S]*?)\]\]>/)
  return m ? m[1] : inner
}

function idFromJobUrl(url: string): string | null {
  const m = url.match(/-(\d+)\/?$/)
  return m ? m[1] : null
}

/**
 * Parse the full-board RSS feed. Item titles have the form
 * "Role at Company"; the company is split off the LAST " at " so roles
 * containing " at " (e.g. "Engineer at Scale in Boston") survive. Location
 * comes from the description's "Location:" header line. Description bodies
 * are deliberately not kept - search results stay lean; `detail` fetches
 * the posting page.
 */
export function parseRss(xml: string): JobCard[] {
  const results: JobCard[] = []
  const items = xml.split(/<item>/).slice(1)

  for (const item of items) {
    const titleRaw = item.match(/<title>([\s\S]*?)<\/title>/)
    const linkRaw = item.match(/<link>([\s\S]*?)<\/link>/)
    if (!titleRaw || !linkRaw) continue
    const titleAll = clean(cdata(titleRaw[1]))
    const link = decodeHtmlEntities(cdata(linkRaw[1]).trim())
    const id = idFromJobUrl(link)
    if (!id || !titleAll) continue

    // "Role at Company" -> split on the last " at ".
    const at = titleAll.lastIndexOf(" at ")
    let title: string = titleAll
    let company: string | null = null
    if (at > 0 && at < titleAll.length - 4) {
      title = titleAll.slice(0, at)
      company = titleAll.slice(at + 4) || null
    }

    const pubRaw = item.match(/<pubDate>([\s\S]*?)<\/pubDate>/)
    let date: string | null = null
    if (pubRaw) {
      const parsed = new Date(cdata(pubRaw[1]).trim())
      date = isNaN(parsed.getTime()) ? clean(cdata(pubRaw[1])) : parsed.toISOString()
    }

    // Location lives in the description header:
    // "<p><strong>Location:</strong> ...</p>".
    let location: string | null = null
    const loc = item.match(/<strong>Location:<\/strong>([\s\S]*?)<\/p>/i)
    if (loc) location = clean(loc[1]) || null

    results.push({
      id,
      title: title || "(untitled)",
      company,
      companyUrl: null,
      location,
      date,
      url: link,
      category: null,
      salary: null,
      tags: [],
    })
  }

  return results
}

/**
 * Parse one category page (at most 90 recent cards). Card anchors split on
 * `<a href="/job/<slug>" aria-label="...">`; badges (`font-normal` spans)
 * are salary (leading $) and location(s) - the first location badge is the
 * primary site, extras are alternate offices.
 */
export function parseCategoryCards(html: string, category: string): JobCard[] {
  const results: JobCard[] = []
  const chunks = html.split('<a href="/job/').slice(1)

  for (const chunk of chunks) {
    const head = chunk.match(/^([a-z0-9-]+)"/)
    if (!head) continue
    const slug = head[1]
    const id = idFromJobUrl(slug)
    if (!id) continue

    const titleMatch = chunk.match(/<h3[^>]*>([\s\S]*?)<\/h3>/i)
    if (!titleMatch) continue
    const title = clean(titleMatch[1])
    if (!title) continue

    const companyMatch = chunk.match(
      /<p class="text-muted-foreground truncate text-base">([\s\S]*?)<\/p>/i,
    )
    const company = companyMatch ? clean(companyMatch[1]) || null : null

    const dateMatch = chunk.match(
      /class="text-muted-foreground ml-auto[^"]*"[^>]*>([\s\S]*?)<\/span>/i,
    )
    const date = dateMatch ? clean(dateMatch[1]) || null : null

    let salary: string | null = null
    let location: string | null = null
    const badgeRe = /font-normal">([\s\S]*?)<\/span>/gi
    let bm: RegExpExecArray | null
    while ((bm = badgeRe.exec(chunk)) !== null) {
      const text = clean(bm[1])
      if (!text) continue
      if (text.startsWith("$") || text.includes("an hour")) {
        salary = salary ?? text
      } else if (location === null) {
        location = text
      }
    }

    results.push({
      id,
      title,
      company,
      companyUrl: null,
      location,
      date,
      url: `${BASE_URL}/job/${slug}`,
      category,
      salary,
      tags: [],
    })
  }

  return results
}

/**
 * Enrich RSS items with what only the category pages know (category, salary,
 * card location). RSS wins for identity fields; category cards win for
 * category/salary and fill a missing location. Returns the merged list plus
 * the ids seen on category pages (used to filter RSS-only postings out of a
 * category-filtered search).
 */
export function mergeCategoryInfo(
  rssItems: JobCard[],
  categoryCards: JobCard[],
): { merged: JobCard[]; categoryIds: Set<string> } {
  const byId = new Map<string, JobCard>()
  for (const card of categoryCards) byId.set(card.id, card)

  const merged = rssItems.map((item) => {
    const card = byId.get(item.id)
    if (!card) return item
    return {
      ...item,
      category: card.category,
      salary: card.salary ?? item.salary,
      location: item.location ?? card.location,
    }
  })
  return { merged, categoryIds: new Set(byId.keys()) }
}

/** Client-side keyword filter over title, company, location, salary, and tags. */
export function matchesQuery(card: JobCard, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  // Split into terms so "research engineer" matches "Applied AI, Research
  // Engineer" even when the exact phrase does not appear.
  const terms = q.split(/\s+/).filter(Boolean)
  const haystack = [
    card.title,
    card.company ?? "",
    card.location ?? "",
    card.salary ?? "",
    ...card.tags,
  ]
    .join(" ")
    .toLowerCase()
  return terms.every((t) => haystack.includes(t))
}

/**
 * Posting age in days from the card's relative date ("3 days ago").
 * Returns null for unparseable text - a card whose date cannot be read must
 * not be silently dropped by --jobage.
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
    case "minute":
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
 * block (description, datePosted, validThrough deadline, employmentType,
 * baseSalary) and the external apply link is the only external anchor with
 * role="button" (the company-careers and social links are plain anchors).
 */
export function parseJobDetail(html: string, id: string): JobDetail {
  const ldStart = html.indexOf('<script type="application/ld+json">')
  let title: string | null = null
  let company: string | null = null
  let description: string | null = null
  let datePosted: string | null = null
  let deadline: string | null = null
  let employmentType: string | null = null
  let salary: string | null = null
  let location: string | null = null

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
          jobLocation?: Array<{
            address?: { addressLocality?: string; addressRegion?: string; addressCountry?: string }
          }>
          baseSalary?: {
            currency?: string
            value?: { minValue?: number; maxValue?: number; unitText?: string }
          }
        }
        title = ld.title ?? null
        company = ld.hiringOrganization?.name ?? null
        datePosted = ld.datePosted ?? null
        deadline = ld.validThrough ?? null
        employmentType = ld.employmentType ?? null
        const first = ld.jobLocation?.[0]?.address
        if (first) {
          location =
            [first.addressLocality, first.addressRegion, first.addressCountry]
              .filter(Boolean)
              .join(", ") || null
        }
        const v = ld.baseSalary?.value
        if (v && (v.minValue !== undefined || v.maxValue !== undefined)) {
          const currency = ld.baseSalary?.currency ?? ""
          const range =
            v.minValue !== undefined && v.maxValue !== undefined && v.minValue !== v.maxValue
              ? `${v.minValue.toLocaleString("en-US")} - ${v.maxValue.toLocaleString("en-US")}`
              : String(v.minValue ?? v.maxValue)
          salary = `${currency} ${range}${v.unitText ? ` / ${v.unitText.toLowerCase()}` : ""}`.trim()
        }
        if (ld.description) {
          const withBreaks = ld.description
            .replace(/<\s*br\s*\/?>/gi, "\n")
            .replace(/<\/(p|li|ul|ol|div|h\d)>/gi, "\n")
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

  // External apply link: the only external anchor rendered as a button.
  const applyMatch = html.match(
    /<a href="(https?:\/\/[^"]+)"[^>]*role="button"[^>]*>/i,
  )
  const applyUrl =
    applyMatch && !applyMatch[1].includes("moaijobs.com")
      ? decodeHtmlEntities(applyMatch[1])
      : null

  const canonical = html.match(/<link rel="canonical" href="([^"]+)"/i)
  const url = canonical ? decodeHtmlEntities(canonical[1]) : `${BASE_URL}/job/unknown-${id}`

  return {
    id,
    title: title || "(untitled)",
    company,
    companyUrl: null,
    location,
    date: datePosted,
    url,
    category: "detail",
    salary,
    tags: [],
    description,
    deadline,
    employmentType,
    applyUrl,
  }
}

/**
 * Resolve a job id (or any /job/ URL) to its canonical URL. Detail URLs
 * include the slug, so a bare numeric id needs one lookup; the RSS feed is
 * the complete id->url index (the sitemap lists only category pages).
 * Returns null when the id is not on the board.
 */
export async function resolveJobUrl(idOrUrl: string): Promise<string | null> {
  if (/^https?:\/\//.test(idOrUrl)) {
    if (idOrUrl.includes("/job/")) return idOrUrl.split("#")[0]
    return null
  }
  if (!/^\d+$/.test(idOrUrl)) return null
  const xml = await htmlFetch(`${BASE_URL}${RSS_PATH}`)
  if (!xml) return null
  // Split per <item> so one malformed entry cannot break the scan.
  for (const item of xml.split(/<item>/).slice(1)) {
    const link = item.match(/<link>([\s\S]*?)<\/link>/)
    if (!link) continue
    const url = decodeHtmlEntities(cdata(link[1]).trim())
    if (url.endsWith(`-${idOrUrl}`)) return url
  }
  return null
}
