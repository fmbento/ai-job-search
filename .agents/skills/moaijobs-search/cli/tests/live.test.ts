import { describe, expect, test } from "bun:test";
import { runCLI, parseJSON } from "./helpers";

interface SearchResponse {
  meta: { count: number; page: number };
  results: Array<{
    id: string;
    title: string;
    company: string | null;
    location: string | null;
    date: string | null;
    url: string;
    category: string | null;
    salary: string | null;
    tags: string[];
  }>;
}

describe("live: moaijobs.com", () => {
  test("whole board via RSS: parses a healthy number of postings", async () => {
    const res = await runCLI(["search", "--format", "json"]);
    const data = parseJSON<SearchResponse>(res);
    expect(data.meta.count).toBeGreaterThanOrEqual(100);
    expect(data.results).toHaveLength(data.meta.count);
    const first = data.results[0]!;
    expect(first.id).toMatch(/^\d+$/);
    expect(first.title.length).toBeGreaterThan(0);
    expect(first.url).toContain("moaijobs.com/job/");
    expect(first.date).not.toBeNull();
  });

  test("search -q LLM returns only LLM postings", async () => {
    const res = await runCLI(["search", "-q", "LLM", "--format", "json"]);
    const data = parseJSON<SearchResponse>(res);
    expect(data.meta.count).toBeGreaterThanOrEqual(1);
    for (const r of data.results) {
      const haystack = [r.title, r.company, r.location, r.salary]
        .join(" ")
        .toLowerCase();
      expect(haystack).toContain("llm");
    }
  });

  test("search -c ai-agents tags every result with the category", async () => {
    const res = await runCLI(["search", "-c", "ai-agents", "--format", "json"]);
    const data = parseJSON<SearchResponse>(res);
    expect(data.meta.count).toBeGreaterThanOrEqual(1);
    expect(data.meta.count).toBeLessThanOrEqual(90); // category pages cap at 90
    for (const r of data.results) {
      expect(r.category).toBe("ai-agents");
    }
  });

  test("unknown category exits 1 with BAD_CATEGORY", async () => {
    const res = await runCLI(["search", "-c", "not-a-category"]);
    expect(res.exitCode).toBe(1);
    expect(res.stderr).toContain("BAD_CATEGORY");
  });

  test("unknown flag exits 1 with UNKNOWN_FLAG", async () => {
    const res = await runCLI(["search", "--bogus-flag", "x"]);
    expect(res.exitCode).toBe(1);
    expect(res.stderr).toContain("UNKNOWN_FLAG");
  });

  test("detail resolves a live posting and reads JSON-LD fields", async () => {
    // Pick a posting from the live board so the test never depends on one
    // hardcoded id staying open.
    const search = await runCLI(["search", "-q", "LLM", "-n", "1", "--format", "json"]);
    const found = parseJSON<SearchResponse>(search);
    expect(found.results.length).toBeGreaterThanOrEqual(1);
    const id = found.results[0]!.id;

    const res = await runCLI(["detail", id, "--format", "json"]);
    const d = parseJSON<{
      id: string;
      title: string;
      description: string | null;
      url: string;
      applyUrl: string | null;
      deadline: string | null;
      employmentType: string | null;
    }>(res);
    expect(d.title.length).toBeGreaterThan(0);
    expect(d.url).toContain("/job/");
    expect(d.description).not.toBeNull();
    expect(d.description!.length).toBeGreaterThan(50);
  });

  test("detail with an unknown id exits 1 with BAD_ID", async () => {
    const res = await runCLI(["detail", "999999999"]);
    expect(res.exitCode).toBe(1);
    expect(res.stderr).toContain("BAD_ID");
  });
});
