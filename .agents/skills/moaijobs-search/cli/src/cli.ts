#!/usr/bin/env bun
// Self-contained CLI for searching AI jobs on MoAIJobs (moaijobs.com).
// No external CLI framework, so it runs anywhere `bun` is available with
// zero install beyond the repo clone.
//
// The portal has no server-side search and no JSON API; the complete board is
// published in one RSS feed, which this CLI fetches and filters client-side.
// Category pages are fetched only for --category filtering. Public pages
// only, robots.txt permits access, no credentials required.

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

const HELP = `moaijobs-cli — search AI jobs on moaijobs.com

The portal has no server-side search; the complete board (~293 postings) is
published in one RSS feed, which this CLI fetches and filters client-side.
Category pages (--category) hold only the 90 most recent postings each and
are fetched only when you filter by category.

USAGE
  bun run src/cli.ts search [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, provider). Optional:
                          without it you get the whole board.
  --category, -c <name>   Restrict to one category. Repeatable. Categories:
                          ${CATEGORY_SLUGS.join(", ")}. Note: category pages only
                          list the 90 most recent postings each, so a category
                          filter can hide older matches that a plain search sees.
  --jobage <days>         Posted within N days (relative card dates).
  --page <n>              1-indexed page of results (client-side slicing).
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

  There is no --location flag: filter locations client-side (e.g. with jq),
  or include the place in --query.

EXAMPLES
  bun run src/cli.ts search -q "LLM" --format table
  bun run src/cli.ts search -q "research engineer" --jobage 14 --format table
  bun run src/cli.ts search -q "MLOps" -c ml-engineer --format table
  bun run src/cli.ts search -q "agent" -c ai-agents -c remote-ai --format table
  bun run src/cli.ts detail 5585 --format plain

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
