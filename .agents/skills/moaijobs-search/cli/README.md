# moaijobs-cli

Search AI jobs on [moaijobs.com](https://www.moaijobs.com) from the terminal.
Zero runtime dependencies — needs only [bun](https://bun.sh).

```bash
bun run src/cli.ts search -q "LLM" --format table
bun run src/cli.ts detail 6034 --format plain
```

## Commands

| Command | Purpose |
|---------|---------|
| `search [flags]` | Fetch the board (RSS, one request) and filter client-side |
| `detail <id\|url>` | Full description, deadline, salary, employment type, apply link |

### Search flags

| Flag | Effect |
|------|--------|
| `-q`, `--query <text>` | Keywords over title/company/location/salary (AND across terms). Optional. |
| `-c`, `--category <name>` | Restrict to a category. Repeatable / comma-separated. |
| `--jobage <days>` | Posted within N days (relative dates; unparseable kept). |
| `--page <n>` | 1-indexed page of results (client-side). |
| `-n`, `--limit <n>` | Cap results emitted. |
| `--format <fmt>` | `json` (default) \| `table` \| `plain`. |

Categories: `ai-engineer`, `ml-engineer`, `research-engineer`,
`research-scientist`, `data-science`, `ai-agents`, `remote-ai`.

**Caveat:** the portal has no server-side search; the RSS feed is the complete
board, while category pages serve at most the 90 most recent postings each. A
`-c` filter can hide older matches that a plain `search -q` sees.

## Examples

```bash
bun run src/cli.ts search -q "research engineer" --jobage 14 --format table
bun run src/cli.ts search -q "MLOps" -c ml-engineer --format table
bun run src/cli.ts search -q "agent" -c ai-agents -c remote-ai --format table
```

Errors go to stderr as `{ "error": "...", "code": "..." }` with exit code 1.
Unknown flags are rejected (`UNKNOWN_FLAG`) instead of silently ignored.

## Development

```bash
bun install        # dev types only (typescript, @types/bun)
bun run typecheck  # tsc --noEmit
bun test           # offline parsing tests + live tests against the board
```

`tests/parsing.test.ts` runs offline; `tests/live.test.ts` hits the real
board and needs network access. Parsing anchors and endpoint notes live in
`../url-reference.md`.
