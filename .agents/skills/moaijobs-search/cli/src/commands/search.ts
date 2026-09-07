import {
  BASE_URL,
  CATEGORY_PATHS,
  RSS_PATH,
  htmlFetch,
  matchesQuery,
  mergeCategoryInfo,
  parseCategoryCards,
  parseRss,
  relativeDateToDays,
  writeError,
  type CategorySlug,
  type JobCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  category: string[] // empty = no category filter, RSS-only
  jobage: number // 9999 = no filter
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

/** Client-side age filter over relative dates; unparseable dates survive. */
function filterByAge(cards: JobCard[], maxAgeDays: number): JobCard[] {
  return cards.filter((c) => {
    const days = relativeDateToDays(c.date)
    return days === null || days <= maxAgeDays
  })
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const rows = cards.map((c) => {
    const id = c.id.padEnd(6)
    const title = (c.title || "").slice(0, 38).padEnd(38)
    const company = (c.company || "—").slice(0, 20).padEnd(20)
    const location = (c.location || "—").slice(0, 20).padEnd(20)
    const salary = (c.salary || "—").slice(0, 22)
    return `${id} ${title} ${company} ${location} ${salary}`
  })
  const header =
    "ID".padEnd(6) +
    " " +
    "TITLE".padEnd(38) +
    " " +
    "PROVIDER".padEnd(20) +
    " " +
    "LOCATION".padEnd(20) +
    " SALARY"
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    // Validate category names before fetching anything, so a typo like
    // "ml-enginer" errors instead of silently returning the whole board.
    if (opts.category.length > 0) {
      const invalid = opts.category.filter((c) => !(c in CATEGORY_PATHS))
      if (invalid.length > 0) {
        writeError(
          `unknown category "${invalid.join('", "')}" - valid categories: ${CATEGORY_SLUGS_LIST}`,
          "BAD_CATEGORY",
        )
        return 1
      }
    }

    // 1. The RSS feed IS the board - complete, one request.
    const xml = await htmlFetch(`${BASE_URL}${RSS_PATH}`)
    if (!xml) {
      writeError("RSS feed unavailable (empty or 404)", "FEED_UNAVAILABLE")
      return 1
    }
    let cards = parseRss(xml)
    if (cards.length === 0) {
      writeError("RSS feed parsed to zero postings - markup may have changed", "FEED_EMPTY")
      return 1
    }

    // 2. Category filter: fetch only the requested category pages, enrich,
    //    and drop RSS postings not actually listed in those categories.
    if (opts.category.length > 0) {
      const settled = await Promise.allSettled(
        (opts.category as CategorySlug[]).map(async (cat) => {
          const html = await htmlFetch(`${BASE_URL}${CATEGORY_PATHS[cat]}`)
          if (!html) throw new Error(`category page unavailable: ${cat}`)
          return parseCategoryCards(html, cat)
        }),
      )
      const catCards: JobCard[] = []
      const failed: string[] = []
      for (const s of settled) {
        if (s.status === "fulfilled") catCards.push(...s.value)
        else failed.push(String(s.reason))
      }
      if (catCards.length === 0) {
        writeError(`all requested category fetches failed: ${failed.join("; ")}`, "CATEGORY_FAILED")
        return 1
      }
      const { merged, categoryIds } = mergeCategoryInfo(cards, catCards)
      cards = merged
      // Local const so the closure sees a narrowed Set (a captured `let`
      // keeps its declared nullable type inside callbacks).
      const allowedIds = categoryIds
      cards = cards.filter((c) => allowedIds.has(c.id))
    }

    if (opts.query) cards = cards.filter((c) => matchesQuery(c, opts.query as string))
    if (opts.jobage < 9999) cards = filterByAge(cards, opts.jobage)

    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map(
            (c) =>
              `${c.title}\n  ${c.company || "—"} · ${c.location || "—"} · ${c.date || "—"}\n  id: ${c.id}\n  ${c.url}`,
          )
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify({ meta: { count: cards.length, page: opts.page }, results: cards }, null, 2) +
          "\n",
      )
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}

const CATEGORY_SLUGS_LIST = Object.keys(CATEGORY_PATHS).join(", ")
