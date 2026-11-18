// What the site gets from NoClick: the app itself, which sends its email, and the database bound to
// it as DB. `Project.current()` is signed in by the deployment, so the site holds no API key.
import { Project } from "noclick";

export async function site() {
  const app = await Project.current().hydrate();
  return { app, db: await app.database("DB") };
}

export const PUBLICATION = {
  name: "Field Notes",
  tagline: "Climate tech in five minutes, every Monday.",
};
