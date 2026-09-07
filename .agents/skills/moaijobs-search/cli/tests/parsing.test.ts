import { describe, expect, test } from "bun:test";
import {
  matchesQuery,
  mergeCategoryInfo,
  parseCategoryCards,
  parseJobDetail,
  parseRss,
  relativeDateToDays,
  type JobCard,
} from "../src/helpers";

// Minimal RSS item mirroring the live feed's shape (built from the structure
// recorded in url-reference.md).
function rssItem(overrides: {
  title?: string;
  slug?: string;
  location?: string;
  pubDate?: string;
}): string {
  const title = overrides.title ?? "Applied AI, Research Engineer at Anthropic";
  const slug = overrides.slug ?? "applied-ai-research-engineer-anthropic-5585";
  const location = overrides.location ?? "San Francisco, CA, USA";
  const pubDate = overrides.pubDate ?? "Fri, 04 Sep 2026 22:13:05 GMT";
  return `<item>
            <title><![CDATA[${title}]]></title>
            <link>https://www.moaijobs.com/job/${slug}</link>
            <pubDate>${pubDate}</pubDate>
            <description><![CDATA[
        <![CDATA[
          <h2>Role</h2>
          <p><strong>Company:</strong> Anthropic</p>
          <p><strong>Location:</strong> ${location}</p>
          <h3>Job Description:</h3>
          &lt;p&gt;Build things&lt;/p&gt;
        ]]>
            ]]></description>
        </item>`;
}

const CATEGORY_CARD = `<a href="/job/applied-ai-research-engineer-anthropic-5585" aria-label="View job details"><div data-slot="card"><div data-slot="card-content"><div class="flex flex-wrap"><div class="flex size-14 shrink-0"><img src="logo.png" alt="Anthropic logo"/></div><span class="text-muted-foreground ml-auto shrink-0 text-sm whitespace-nowrap sm:order-last sm:ml-0">3 days ago</span><div class="w-full"><h3 class="truncate text-xl font-semibold">Applied AI, Research Engineer</h3><p class="text-muted-foreground truncate text-base">Anthropic</p><div class="mt-3 flex items-center gap-1.5 overflow-hidden"><span data-slot="badge" class="font-normal">$300K - $400K</span><span data-slot="badge" class="font-normal">San Francisco, CA</span><span data-slot="badge" class="font-normal">Seattle, WA</span></div></div></div></div></div></a>`;

describe("parseRss", () => {
  const xml = `<?xml version="1.0"?><rss><channel>${rssItem({})}${rssItem({
    title: "Engineer at Scale at Cohere",
    slug: "engineer-at-scale-cohere-123",
  })}</channel></rss>`;

  test("splits company off the LAST ' at '", () => {
    const cards = parseRss(xml);
    expect(cards).toHaveLength(2);
    expect(cards[0].title).toBe("Applied AI, Research Engineer");
    expect(cards[0].company).toBe("Anthropic");
    // A role containing " at " must not be mangled.
    expect(cards[1].title).toBe("Engineer at Scale");
    expect(cards[1].company).toBe("Cohere");
  });

  test("extracts id, url, ISO date, and location from the description header", () => {
    const cards = parseRss(xml);
    expect(cards[0].id).toBe("5585");
    expect(cards[0].url).toBe("https://www.moaijobs.com/job/applied-ai-research-engineer-anthropic-5585");
    expect(cards[0].date).toBe("2026-09-04T22:13:05.000Z");
    expect(cards[0].location).toBe("San Francisco, CA, USA");
  });

  test("does not keep description bodies - search stays lean", () => {
    const cards = parseRss(xml) as unknown as Array<Record<string, unknown>>;
    expect(cards[0].description).toBeUndefined();
  });
});

describe("parseCategoryCards", () => {
  test("parses title, company, salary, first location as primary", () => {
    const cards = parseCategoryCards(CATEGORY_CARD, "ai-engineer");
    expect(cards).toHaveLength(1);
    const c = cards[0];
    expect(c.id).toBe("5585");
    expect(c.title).toBe("Applied AI, Research Engineer");
    expect(c.company).toBe("Anthropic");
    expect(c.salary).toBe("$300K - $400K");
    expect(c.location).toBe("San Francisco, CA");
    expect(c.category).toBe("ai-engineer");
    expect(c.date).toBe("3 days ago");
  });

  test("a malformed card is skipped without breaking siblings", () => {
    const broken = CATEGORY_CARD.replace(/-(\d+)"/, '-x"'); // no trailing id
    const cards = parseCategoryCards(CATEGORY_CARD + broken, "ai-engineer");
    expect(cards).toHaveLength(1);
  });
});

describe("mergeCategoryInfo", () => {
  test("category wins, rss keeps identity, missing location is filled", () => {
    const rss = parseRss(`<?xml?><rss><channel>${rssItem({ location: "Remote" })}</channel></rss>`);
    const cat = parseCategoryCards(CATEGORY_CARD, "ai-engineer");
    const { merged, categoryIds } = mergeCategoryInfo(rss, cat);
    expect(merged[0].category).toBe("ai-engineer");
    expect(merged[0].salary).toBe("$300K - $400K");
    expect(merged[0].location).toBe("Remote"); // rss wins
    expect(categoryIds.has("5585")).toBe(true);
  });
});

describe("matchesQuery", () => {
  const base: JobCard = {
    id: "1",
    title: "Senior Machine Learning Engineer",
    company: "Hugging Face",
    companyUrl: null,
    location: "Remote",
    date: "2 days ago",
    url: "https://www.moaijobs.com/job/x-1",
    category: "ml-engineer",
    salary: null,
    tags: [],
  };

  test("empty query matches everything", () => {
    expect(matchesQuery(base, "")).toBe(true);
  });

  test("terms AND across title and company", () => {
    expect(matchesQuery(base, "machine hugging")).toBe(true);
    expect(matchesQuery(base, "machine nonexistent")).toBe(false);
  });
});

describe("relativeDateToDays", () => {
  test("parses the portal's relative formats", () => {
    expect(relativeDateToDays("New")).toBe(0);
    expect(relativeDateToDays("3 days ago")).toBe(3);
    expect(relativeDateToDays("2 weeks ago")).toBe(14);
    expect(relativeDateToDays("1 month ago")).toBe(30);
  });

  test("unparseable text returns null so --jobage cannot silently drop it", () => {
    expect(relativeDateToDays("recently")).toBeNull();
    expect(relativeDateToDays(null)).toBeNull();
  });
});

describe("parseJobDetail", () => {
  const ld = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: "Applied AI, Research Engineer",
    description: "<h3>About</h3><p>Build safe AI.<br>With care</p>",
    datePosted: "2026-09-04T15:26:23.000Z",
    validThrough: "2026-11-03T16:26:23.000Z",
    employmentType: "FULL_TIME",
    hiringOrganization: { name: "Anthropic" },
    jobLocation: [{ address: { addressLocality: "San Francisco", addressRegion: "CA", addressCountry: "US" } }],
    baseSalary: { currency: "USD", value: { minValue: 300000, maxValue: 400000, unitText: "YEAR" } },
  });
  const html = `<html><head><link rel="canonical" href="https://www.moaijobs.com/job/applied-ai-research-engineer-anthropic-5585"/></head><body><script type="application/ld+json">${ld}</script><a href="http://anthropic.com/careers" rel="nofollow noreferrer noopener">careers</a><a href="https://job-boards.greenhouse.io/anthropic/jobs/5390811008" target="_blank" rel="noopener nofollow" role="button">Apply</a></body></html>`;

  test("parses JSON-LD fields, salary range, and the role=button apply link", () => {
    const d = parseJobDetail(html, "5585");
    expect(d.title).toBe("Applied AI, Research Engineer");
    expect(d.company).toBe("Anthropic");
    expect(d.date).toBe("2026-09-04T15:26:23.000Z");
    expect(d.deadline).toBe("2026-11-03T16:26:23.000Z");
    expect(d.employmentType).toBe("FULL_TIME");
    expect(d.salary).toContain("300,000");
    expect(d.salary).toContain("400,000");
    expect(d.location).toBe("San Francisco, CA, US");
    expect(d.applyUrl).toBe("https://job-boards.greenhouse.io/anthropic/jobs/5390811008");
    expect(d.description).toContain("About");
    expect(d.description).toContain("Build safe AI.\nWith care");
  });

  test("malformed JSON-LD falls back to h1 instead of throwing", () => {
    const broken = `<html><body><script type="application/ld+json">{oops</script><h1>Fallback</h1></body></html>`;
    expect(parseJobDetail(broken, "1").title).toBe("Fallback");
  });
});
