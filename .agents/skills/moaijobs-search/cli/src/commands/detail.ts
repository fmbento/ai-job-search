import { htmlFetch, parseJobDetail, resolveJobUrl, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string // bare numeric id, or a full /job/ URL
  format: "json" | "plain"
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  try {
    const url = await resolveJobUrl(opts.id)
    if (!url) {
      writeError(
        `Could not resolve "${opts.id}" to a job URL - pass the numeric id from search results or a full moaijobs.com/job/ URL`,
        "BAD_ID",
      )
      return 1
    }
    const html = await htmlFetch(url)
    if (!html) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const id = opts.id.replace(/^\D*/, "") || url.match(/-(\d+)\/?$/)?.[1] || opts.id
    const job = parseJobDetail(html, id)

    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${job.location || "—"}`,
        job.date ? `Posted: ${job.date}` : "",
        job.deadline ? `Deadline: ${job.deadline}` : "",
        job.employmentType ? `Employment: ${job.employmentType}` : "",
        job.salary ? `Salary: ${job.salary}` : "",
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
