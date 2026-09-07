import { describe, expect, test } from "bun:test";
import { runCLI } from "./helpers";

// Live smoke tests against realworkfromanywhere.com (public pages, robots.txt
// permits access). These exercise the real fetch path end to end; the parsing
// unit tests live in parsing.test.ts.

describe("live search (realworkfromanywhere.com)", () => {
  test("search -q developer returns results with id/title/url", async () => {
    const res = await runCLI(["search", "-q", "developer", "--format", "json"]);
    expect(res.exitCode).toBe(0);

    const parsed = JSON.parse(res.stdout) as {
      meta: { count: number; page: number };
      results: Array<{ id: string; title: string | null; url: string }>;
    };
    expect(parsed.meta.page).toBe(1);
    expect(parsed.results.length).toBeGreaterThanOrEqual(1);

    const first = parsed.results[0];
    expect(first.id).toBeTruthy();
    expect(first.title).toBeTruthy();
    expect(first.url).toMatch(/^https:\/\/www\.realworkfromanywhere\.com\/jobs\//);
  }, 60000);

  test("a bogus flag exits 1 with a JSON error on stderr", async () => {
    const res = await runCLI(["search", "--bogus-flag", "x"]);
    expect(res.exitCode).toBe(1);
    expect(res.stdout).toBe("");
    const err = JSON.parse(res.stderr) as { error: string; code: string };
    expect(err.code).toBe("UNKNOWN_FLAG");
    expect(err.error).toBeTruthy();
  }, 30000);

  test("detail without an id exits 1 with a JSON error on stderr", async () => {
    const res = await runCLI(["detail"]);
    expect(res.exitCode).toBe(1);
    const err = JSON.parse(res.stderr) as { error: string; code: string };
    expect(err.code).toBe("NO_ID");
  }, 30000);
});
