// Confirming takes a click on the page, not just opening the link: mail scanners open every link in
// an email, and they shouldn't subscribe anyone. It also lifts an earlier unsubscribe.
import { redirect } from "next/navigation";
import { PUBLICATION, site } from "../../../lib/noclick";

export default async function Confirm({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;

  async function confirm() {
    "use server";
    const { app, db } = await site();
    const found = await db.query("select email from subscribers where token = ?", [token]);
    const email = found.rows[0]?.email;
    if (typeof email === "string") {
      await db.execute("update subscribers set confirmed_at = datetime('now') where token = ?", [token]);
      // Broadcasts skip anyone who unsubscribed; a confirmed signup is how they opt in again.
      await app.email.resubscribe(email);
    }
    redirect("/");
  }

  return (
    <main>
      <h1>{PUBLICATION.name}</h1>
      <form action={confirm}>
        <button>Confirm my subscription</button>
      </form>
    </main>
  );
}
