// Issues are Markdown the agents wrote from pages they read on the web, so raw HTML in them is
// dropped rather than rendered: a page can't smuggle a script into the site or an email.
import { Marked } from "marked";

const marked = new Marked({ renderer: { html: () => "" } });

export function render(markdown: string): string {
  return marked.parse(markdown, { async: false });
}
