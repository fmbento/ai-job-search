import { describe, expect, test } from "bun:test";
import {
  matchesQuery,
  parseJobCards,
  parseJobDetail,
  relativeDateToDays,
  type JobCard,
} from "../src/helpers";

// Minimal card chunk mirroring the portal's markup (anchor + logo + title +
// company + date + location + salary + badges). Built from the live page
// structure recorded in url-reference.md.
function card(overrides: {
  slug?: string;
  title?: string;
  company?: string;
  date?: string;
  salary?: string;
  tags?: string[];
}): string {
  const slug = overrides.slug ?? "product-engineer-safetywing-7580";
  const title = overrides.title ?? "Product Engineer";
  const company = overrides.company ?? "SafetyWing";
  const date = overrides.date ?? "1 day ago";
  const salary = overrides.salary
    ? `<div class="flex items-center gap-1.5"><svg></svg><span class="whitespace-nowrap">${overrides.salary}</span></div>`
    : "";
  const tags = (overrides.tags ?? ["mysql", "kubernetes"])
    .map((t) => `<span class="badge border-base-300">${t}</span>`)
    .join("");
  return `<a href="/jobs/${slug}" class="block w-full rounded-lg bg-base-100 ring-1 ring-inset ring-base-300 "><div class="flex flex-col md:flex-row gap-3 md:gap-5 p-4 md:p-5"><div class="flex items-start justify-between md:block md:shrink-0"><div class="shrink-0"><div class="w-12 h-12"><img src="https://example.com/logo.png" alt="${company} logo" class="w-full h-full object-cover"/></div></div><span class="md:hidden text-sm pt-1 text-base-content/80">${date}</span></div><div class="grow min-w-0"><div class="flex justify-between items-start gap-2"><div class="min-w-0"><h3 class="text-xl md:text-xl font-bold text-base-content leading-snug pr-2 mb-0.5">${title}</h3><p class="text-base truncate font-medium text-base-content/90">${company}</p></div><span class="hidden md:block shrink-0 text-sm whitespace-nowrap text-base-content/80">${date}</span></div><div class="flex items-center gap-4 md:gap-6 flex-wrap py-3 text-sm"><div class="flex items-center gap-1.5 text-base-content/80"><svg class="size-4"></svg><span class="truncate"><span>Anywhere in the World</span></span></div>${salary}</div><div class="flex flex-wrap gap-2">${tags}</div></div></div></a>`;
}

describe("parseJobCards", () => {
  test("parses title, company, id, url, location, salary, and tags", () => {
    const html = `<main>${card({ salary: "$119,900 - $193,200 USD" })}</main>`;
    const cards = parseJobCards(html, "software-developer");
    expect(cards).toHaveLength(1);
    const c = cards[0];
    expect(c.id).toBe("7580");
    expect(c.title).toBe("Product Engineer");
    expect(c.company).toBe("SafetyWing");
    expect(c.url).toBe("https://www.realworkfromanywhere.com/jobs/product-engineer-safetywing-7580");
    expect(c.location).toBe("Anywhere in the World");
    expect(c.salary).toBe("$119,900 - $193,200 USD");
    expect(c.tags).toEqual(["mysql", "kubernetes"]);
    expect(c.category).toBe("software-developer");
  });

  test("handles entities and typographic characters in title/company", () => {
    const html = card({ title: "Java Developer &amp; SRE", company: "Atlassian &amp; Co" });
    const cards = parseJobCards(html, "backend");
    expect(cards[0].title).toBe("Java Developer & SRE");
    expect(cards[0].company).toBe("Atlassian & Co");
  });

  test("salary stays null when the posting lists no range", () => {
    const cards = parseJobCards(`<main>${card({})}</main>`, "backend");
    expect(cards[0].salary).toBeNull();
  });

  test("New badge parses as a zero-day date", () => {
    const cards = parseJobCards(`<main>${card({ date: "New" })}</main>`, "backend");
    expect(cards[0].date).toBe("New");
  });

  test("a malformed card is skipped without breaking its siblings", () => {
    const html = `<main>${card({ slug: "broken-card-no-title-1111" }).replace(
      /<h3[\s\S]*?<\/h3>/,
      "",
    )}${card({ slug: "good-card-acme-2222", title: "Good Card", company: "Acme" })}</main>`;
    const cards = parseJobCards(html, "backend");
    expect(cards).toHaveLength(1);
    expect(cards[0].id).toBe("2222");
    expect(cards[0].title).toBe("Good Card");
  });

  test("nav links to /jobs/ outside cards are not parsed as results", () => {
    const html = `<nav><a href="/jobs/some-nav-link-9999">nav</a></nav><main>${card({})}</main>`;
    const cards = parseJobCards(html, "backend");
    expect(cards).toHaveLength(1);
  });
});

describe("matchesQuery", () => {
  const base: JobCard = {
    id: "1",
    title: "Senior Software Engineer - Ledger",
    company: "Alpaca",
    companyUrl: null,
    location: "Anywhere in the World",
    date: "3 days ago",
    url: "https://www.realworkfromanywhere.com/jobs/x-1",
    category: "backend",
    salary: null,
    tags: ["go", "kubernetes"],
  };

  test("empty query matches everything", () => {
    expect(matchesQuery(base, "")).toBe(true);
    expect(matchesQuery(base, "   ")).toBe(true);
  });

  test("single term matches title case-insensitively", () => {
    expect(matchesQuery(base, "engineer")).toBe(true);
    expect(matchesQuery(base, "ENGINEER")).toBe(true);
  });

  test("multiple terms AND together across fields", () => {
    expect(matchesQuery(base, "software alpaca")).toBe(true);
    expect(matchesQuery(base, "software nonexistent")).toBe(false);
  });

  test("matches tags and salary, not just title", () => {
    expect(matchesQuery(base, "kubernetes")).toBe(true);
    const salaried = { ...base, salary: "$100,000 USD" };
    expect(matchesQuery(salaried, "100,000")).toBe(true);
  });
});

describe("relativeDateToDays", () => {
  test("parses the portal's relative formats", () => {
    expect(relativeDateToDays("New")).toBe(0);
    expect(relativeDateToDays("1 day ago")).toBe(1);
    expect(relativeDateToDays("2 weeks ago")).toBe(14);
    expect(relativeDateToDays("3 months ago")).toBe(90);
  });

  test("unparseable text returns null so --jobage cannot silently drop it", () => {
    expect(relativeDateToDays("recently")).toBeNull();
    expect(relativeDateToDays(null)).toBeNull();
  });
});

describe("parseJobDetail", () => {
  const ldHtml = `<html><head><link rel="canonical" href="https://www.realworkfromanywhere.com/jobs/product-engineer-safetywing-7580"/></head><body><script type="application/ld+json">{"@context":"https://schema.org/","@type":"JobPosting","title":"Product Engineer","description":"<h3>About</h3><div>Build things<br>with care</div>","identifier":{"@type":"PropertyValue","name":"SafetyWing","value":"3913113683"},"datePosted":"2026-09-04","validThrough":"2026-11-03","jobLocationType":"TELECOMMUTE","employmentType":"FULL_TIME","hiringOrganization":{"@type":"Organization","name":"SafetyWing"}}</script><article>body</article><div class="mt-auto"><a href="https://safetywing.pinpointhq.com/en/jobs/575119" rel="nofollow noopener" target="_blank"><button class="btn bg-purple-500">Apply</button></a></div></body></html>`;

  test("parses the JSON-LD block and the apply link", () => {
    const d = parseJobDetail(ldHtml, "7580");
    expect(d.title).toBe("Product Engineer");
    expect(d.company).toBe("SafetyWing");
    expect(d.date).toBe("2026-09-04");
    expect(d.deadline).toBe("2026-11-03");
    expect(d.employmentType).toBe("FULL_TIME");
    expect(d.applyUrl).toBe("https://safetywing.pinpointhq.com/en/jobs/575119");
    expect(d.url).toBe("https://www.realworkfromanywhere.com/jobs/product-engineer-safetywing-7580");
    // Tags stripped, line breaks preserved, entities decoded.
    expect(d.description).toContain("About");
    expect(d.description).toContain("Build things\nwith care");
  });

  test("falls back to <h1> and Posted text when JSON-LD is missing", () => {
    const html = `<html><body><h1>Fallback Title</h1><p class="x">Posted <!-- -->2 days ago</p></body></html>`;
    const d = parseJobDetail(html, "42");
    expect(d.title).toBe("Fallback Title");
    expect(d.date).toBe("2 days ago");
    expect(d.applyUrl).toBeNull();
    expect(d.description).toBeNull();
  });

  test("malformed JSON-LD falls back instead of throwing", () => {
    const html = `<html><head><script type="application/ld+json">{oops</script></head><body><h1>Still Works</h1></body></html>`;
    const d = parseJobDetail(html, "7");
    expect(d.title).toBe("Still Works");
  });
});
