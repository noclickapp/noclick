// The app's schedule calls this every ten minutes. It emails each published issue that hasn't gone
// out yet to every confirmed reader as a broadcast, then marks it sent, so an issue goes out once.
// The broadcast gives each reader their own one-click unsubscribe and skips anyone who used it.
import { render } from "../../../lib/markdown";
import { site } from "../../../lib/noclick";

export async function POST(request: Request) {
  const { app, db } = await site();
  await app.verifyRequest(await request.text(), request.headers);

  const issues = await db.query("select slug, subject, body from issues where emailed_at is null order by slug");
  if (issues.rows.length === 0) return Response.json({ sent: 0 });
  const readers = await db.query("select email from subscribers where confirmed_at is not null");

  for (const issue of issues.rows) {
    const body = String(issue.body);
    const sending = await app.email.broadcast({
      to: readers.rows.map((reader) => String(reader.email)),
      subject: String(issue.subject),
      html: render(body) + `<p><a href="${app.url}/${issue.slug}">Read it on the web</a></p>`,
      text: `${body}\n\nRead it on the web: ${app.url}/${issue.slug}`,
      idempotencyKey: `issue-${issue.slug}`,
    });
    await sending.wait();
    await db.execute("update issues set emailed_at = datetime('now') where slug = ?", [issue.slug]);
  }
  return Response.json({ sent: issues.rows.length, readers: readers.rows.length });
}
