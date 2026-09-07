import {
  BASE_URL,
  CATEGORY_PATHS,
  DEFAULT_CATEGORIES,
  htmlFetch,
  matchesQuery,
  parseJobCards,
  relativeDateToDays,
  writeError,
  type CategorySlug,
  type JobCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  category: string[] // empty = DEFAULT_CATEGORIES
  jobage: number // 9999 = no filter
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

/**
 * Fetch the selected category pages in parallel and parse them. A category
 * page that 404s is skipped rather than fatal — only a total failure of every
 * requested category is an error, so one stale category slug cannot take the
 * whole search down.
 */
export async function fetchCards(categories: CategorySlug[]): Promise<JobCard[]> {
  const settled = await Promise.allSettled(
    categories.map(async (cat) => {
      const html = await htmlFetch(`${BASE_URL}${CATEGORY_PATHS[cat]}`)
      return parseJobCards(html, cat)
    }),
  )
  const cards: JobCard[] = []
  const failed: string[] = []
  for (const s of settled) {
    if (s.status === "fulfilled") {
      cards.push(...s.value)
    } else {
      failed.push(s.reason instanceof Error ? s.reason.message : String(s.reason))
    }
  }
  if (cards.length === 0 && failed.length > 0) {
    throw new Error(`all requested category fetches failed: ${failed.join("; ")}`)
  }
  return cards
}

/** Dedupe by id, preserving first-seen order (pages never overlap in practice). */
export function dedupe(cards: JobCard[]): JobCard[] {
  const seen = new Set<string>()
  return cards.filter((c) => {
    if (seen.has(c.id)) return false
    seen.add(c.id)
    return true
  })
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const rows = cards.map((c) => {
    const id = c.id.padEnd(6)
    const title = (c.title || "").slice(0, 40).padEnd(40)
    const company = (c.company || "—").slice(0, 22).padEnd(22)
    const date = (c.date || "—").slice(0, 14).padEnd(14)
    const salary = (c.salary || "—").slice(0, 24)
    return `${id} ${title} ${company} ${date} ${salary}`
  })
  const header =
    "ID".padEnd(6) +
    " " +
    "TITLE".padEnd(40) +
    " " +
    "COMPANY".padEnd(22) +
    " " +
    "DATE".padEnd(14) +
    " SALARY"
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    // One keyword per category name: the CLI validates names before this
    // point, so a typo like "backends" would silently fetch nothing.
    let categories: CategorySlug[]
    if (opts.category.length === 0) {
      categories = DEFAULT_CATEGORIES
    } else {
      const invalid = opts.category.filter((c) => !(c in CATEGORY_PATHS))
      if (invalid.length > 0) {
        writeError(
          `unknown category "${invalid.join('", "')}" - valid categories: ${Object.keys(CATEGORY_PATHS).join(", ")}`,
          "BAD_CATEGORY",
        )
        return 1
      }
      categories = opts.category as CategorySlug[]
    }

    let cards = dedupe(await fetchCards(categories))

    if (opts.query) cards = cards.filter((c) => matchesQuery(c, opts.query as string))

    if (opts.jobage < 9999) {
      cards = cards.filter((c) => {
        const days = relativeDateToDays(c.date)
        return days !== null && days <= opts.jobage
      })
    }

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
