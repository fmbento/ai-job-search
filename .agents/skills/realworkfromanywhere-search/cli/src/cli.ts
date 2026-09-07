#!/usr/bin/env bun
// Self-contained CLI for searching jobs on Real Work From Anywhere
// (realworkfromanywhere.com) — fully-remote, worldwide job listings.
// No external CLI framework, so it runs anywhere `bun` is available with
// zero install beyond the repo clone.
//
// The portal has no server-side search and no JSON API; this CLI fetches the
// portal's complete per-category listing pages and filters client-side.
// Public pages only, robots.txt permits access, no credentials required.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { CATEGORY_SLUGS } from "./helpers.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit", c: "category" }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith("--") || (a.startsWith("-") && a.length > 1)) {
      const key = alias[a.replace(/^-+/, "")] ?? a.replace(/^-+/, "")
      const next = argv[i + 1]
      if (next === undefined || next.startsWith("-")) {
        flags[key] = true
      } else if (key in flags && key !== "_") {
        // Repeating a flag accumulates (--category a --category b), so the
        // last occurrence cannot silently win.
        const prev = flags[key]
        const list = Array.isArray(prev) ? prev : [String(prev)]
        list.push(next)
        flags[key] = list
        i++
      } else {
        flags[key] = next
        i++
      }
    } else {
      ;(flags._ as string[]).push(a)
    }
  }
  return flags
}

const HELP = `realworkfromanywhere-cli — search fully-remote jobs on realworkfromanywhere.com

The portal publishes complete listings per category page (no pagination, no
server-side search). This CLI fetches the category pages, merges them, and
filters by keyword client-side.

USAGE
  bun run src/cli.ts search [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, or role). Optional:
                          without it you get every listing on the category pages.
  --category, -c <name>   Restrict to one category. Repeatable. Default: all of
                          ${CATEGORY_SLUGS.join(", ")}.
  --jobage <days>         Posted within N days (relative dates on cards).
  --page <n>              1-indexed page of results (client-side slicing).
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

  Location: every listing on the portal is fully remote worldwide, so there is
  no --location flag; results carry "Anywhere in the World".

EXAMPLES
  bun run src/cli.ts search -q "developer" --format table
  bun run src/cli.ts search -q "software engineer" --jobage 14 --format table
  bun run src/cli.ts search -q "postgres" -c backend --format table
  bun run src/cli.ts search -q "support" -c customer-support --format table
  bun run src/cli.ts detail 7580 --format plain

Personal use only — free public board; keep request volume low.
`

// Long-form flag names each command accepts (parseFlags resolves the short
// aliases q/l/n/c to these before validation). "help"/"h" pass so
// `search --help` still prints usage.
const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["query", "category", "jobage", "page", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  // Reject unknown flags instead of silently discarding them: a discarded
  // filter changes what the search returns with no error. add-portal.md's
  // contract requires a bogus flag to exit 1 with a JSON error on stderr.
  const knownFlags = KNOWN_FLAGS[cmd]
  if (knownFlags) {
    for (const key of Object.keys(flags)) {
      if (key === "_" || knownFlags.has(key)) continue
      process.stderr.write(
        JSON.stringify({
          error: `unknown flag --${key} for '${cmd}' - flags are never silently ignored, because a discarded filter changes what the search returns; see --help for the supported flags`,
          code: "UNKNOWN_FLAG",
        }) + "\n",
      )
      return 1
    }
  }

  if (cmd === "search") {
    const fmt = (flags.format as string) || "json"

    const parseIntFlag = (name: string, raw: string | boolean | string[]): number | null => {
      const val = parseInt(raw as string, 10)
      if (isNaN(val)) {
        process.stderr.write(JSON.stringify({ error: `--${name} must be a number, got "${raw}"`, code: "BAD_ARG" }) + "\n")
        return null
      }
      return val
    }

    let jobage = 9999
    if (flags.jobage !== undefined) {
      const v = parseIntFlag("jobage", flags.jobage)
      if (v === null) return 1
      jobage = v
    }
    let page = 1
    if (flags.page !== undefined) {
      const v = parseIntFlag("page", flags.page)
      if (v === null) return 1
      page = Math.max(1, v)
    }
    let limit: number | undefined
    if (flags.limit !== undefined) {
      const v = parseIntFlag("limit", flags.limit)
      if (v === null) return 1
      limit = v
    }

    // Support repeatable --category (comma-separated values also accepted).
    const rawCat = flags.category
    let category: string[] = []
    if (typeof rawCat === "string") {
      category = rawCat.split(",").map((s) => s.trim()).filter(Boolean)
    } else if (Array.isArray(rawCat)) {
      category = (rawCat as string[]).flatMap((s) => s.split(",").map((x) => x.trim())).filter(Boolean)
    }

    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : undefined,
      category,
      jobage,
      page,
      limit,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires an <id|url>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    const opts: DetailOpts = {
      id,
      format: (fmt === "plain" ? "plain" : "json") as DetailOpts["format"],
    }
    return runDetail(opts)
  }

  process.stderr.write(JSON.stringify({ error: `Unknown command "${cmd}"`, code: "BAD_CMD" }) + "\n")
  return 1
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    process.stderr.write(
      JSON.stringify({
        error: e instanceof Error ? e.message : String(e),
        code: "INTERNAL_ERROR",
      }) + "\n",
    )
    process.exit(1)
  })
