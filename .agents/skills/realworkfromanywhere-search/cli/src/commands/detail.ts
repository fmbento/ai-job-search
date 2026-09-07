import { htmlFetch, parseJobDetail, resolveJobUrl, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string // bare numeric id, or a full /jobs/ URL
  format: "json" | "plain"
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  try {
    const url = await resolveJobUrl(opts.id)
    if (!url) {
      writeError(
        `Could not resolve \"${opts.id}\" to a job URL - pass the numeric id from search results or a full realworkfromanywhere.com/jobs/ URL`,
        "BAD_ID",
      )
      return 1
    }
    const html = await htmlFetch(url)
    if (!html) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const job = parseJobDetail(html, opts.id.replace(/^\D*/, ""))

    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${job.location}`,
        job.date ? `Posted: ${job.date}` : "",
        job.deadline ? `Deadline: ${job.deadline}` : "",
        job.employmentType ? `Employment: ${job.employmentType}` : "",
        "",
        job.description || "(no description)",
        "",
        `Apply: ${job.applyUrl || "(see posting page)"}`,
        `URL: ${job.url}`,
      ].filter((l) => l !== "")
      process.stdout.write(lines.join("\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify(job, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
}
