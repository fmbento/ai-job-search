# realworkfromanywhere-cli

Search fully-remote, worldwide job listings on
[Real Work From Anywhere](https://www.realworkfromanywhere.com) — every posting
on the board is remote globally ("Anywhere in the World").

Part of the repo's job-portal skill pattern (see `../SKILL.md` and
`../url-reference.md`).

## Design

- **Zero runtime dependencies** — plain `bun` + `fetch` + chunked regex parsing.
  `bun install` only pulls TypeScript dev types (and is not even required to run).
- The portal has **no server-side search and no JSON API**; it serves one complete
  HTML page per job category. This CLI fetches the category pages in parallel,
  parses the job cards, merges and dedupes them, and filters client-side.
- Scope: `fullstack`, `backend`, `software-developer`, `product`, `design`,
  `sales-and-marketing`, `customer-support` (see `../url-reference.md`; extend
  `CATEGORY_PATHS` in `src/helpers.ts` for more).
- Detail pages expose schema.org `JobPosting` JSON-LD (description, deadline,
  employment type) plus the external apply link.

## Usage

```bash
bun run src/cli.ts search -q "developer" --format table
bun run src/cli.ts search -q "postgres" -c backend --jobage 14 --format table
bun run src/cli.ts search -c customer-support --format table
bun run src/cli.ts detail 7580 --format plain
```

`bun run src/cli.ts --help` documents every flag.

## Development

```bash
bun install        # dev types only
bun run typecheck  # tsc --noEmit
bun run test       # offline parsing tests + live smoke tests
```
