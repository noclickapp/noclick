import { notFound } from "next/navigation";
import { render } from "../../lib/markdown";
import { PUBLICATION, site } from "../../lib/noclick";

export default async function Issue({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const { db } = await site();
  const [issue] = (await db.query("select subject, body from issues where slug = ?", [slug])).rows;
  if (!issue) notFound();
  return (
    <main>
      <p>
        <a href="/">{PUBLICATION.name}</a>
      </p>
      <h1>{String(issue.subject)}</h1>
      <div dangerouslySetInnerHTML={{ __html: render(String(issue.body)) }} />
    </main>
  );
}
