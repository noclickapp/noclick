// The archive and the signup form. A signup is a row, and a subscriber once they confirm from the
// email this sends, so nobody can sign up an address that isn't theirs.
import { randomBytes } from "node:crypto";
import { PUBLICATION, site } from "../lib/noclick";

// Issues are read at request time, so one is live the moment its row is written.
export const dynamic = "force-dynamic";

async function subscribe(form: FormData) {
  "use server";
  const email = String(form.get("email") ?? "").trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return;
  const { app, db } = await site();
  const token = randomBytes(16).toString("hex");
  // Every signup sends a confirmation, a confirmed reader's too: one who unsubscribed and signs up
  // again gets issues again only once they confirm.
  await db.execute(
    `insert into subscribers (email, token) values (?, ?)
     on conflict (email) do update set token = excluded.token`,
    [email, token],
  );
  await app.email.send({
    to: email,
    subject: `Confirm your subscription to ${PUBLICATION.name}`,
    text: `Confirm here: ${app.url}/confirm/${token}\n\nIf you didn't sign up, ignore this email.`,
    idempotencyKey: `confirm-${token}`,
  });
}

export default async function Home() {
  const { db } = await site();
  const issues = await db.query("select slug, subject from issues order by slug desc limit 52");
  return (
    <main>
      <h1>{PUBLICATION.name}</h1>
      <p>{PUBLICATION.tagline}</p>
      <form action={subscribe}>
        <input name="email" type="email" required placeholder="you@example.com" /> <button>Subscribe</button>
      </form>
      <h2>Past issues</h2>
      <ul>
        {issues.rows.map((issue) => (
          <li key={String(issue.slug)}>
            <a href={`/${issue.slug}`}>{String(issue.subject)}</a>
          </li>
        ))}
      </ul>
    </main>
  );
}
