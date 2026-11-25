"""What ``noclick init --template`` writes: small apps that deploy as they are, with nothing to install on your
machine. Each names its files and their text."""

from __future__ import annotations

from typing import Dict

_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{name}</title>
    <link rel="stylesheet" href="/style.css">
  </head>
  <body>
    <main>
      <h1>{name}</h1>
      <p>Edit index.html, then run <code>noclick deploy</code>.</p>
    </main>
  </body>
</html>
"""

_STYLE = """body { font-family: system-ui, sans-serif; margin: 0; display: grid; place-items: center; min-height: 100vh; }
main { max-width: 40rem; padding: 2rem; }
"""

_WORKER = """export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/hello") {
      return Response.json({ hello: "world", at: new Date().toISOString() });
    }
    return env.ASSETS.fetch(request);
  },
};
"""

_WRANGLER = """{{
  "name": "{name}",
  "main": "src/index.js",
  "compatibility_date": "2026-11-01",
  "assets": {{ "directory": "./public", "binding": "ASSETS" }}
}}
"""

_SERVER = '''"""A small web server on Python's standard library: NoClick runs it in a container, on the port it names."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/hello":
            body, kind = json.dumps({{"hello": "world"}}).encode(), "application/json"
        else:
            body, kind = b"<h1>{name}</h1><p>Edit main.py, then run noclick deploy.</p>", "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
'''

#: Each template: what it is, and its files (``{name}`` is the app's name).
TEMPLATES: Dict[str, Dict[str, object]] = {
    "static": {"about": "A site of files: HTML and CSS, served as they are.",
               "files": {"index.html": _PAGE, "style.css": _STYLE}},
    "worker": {"about": "A Worker in front of a folder of files: an API route and the site, on the edge.",
               "files": {"wrangler.jsonc": _WRANGLER, "src/index.js": _WORKER, "public/index.html": _PAGE,
                         "public/style.css": _STYLE}},
    "python": {"about": "A Python web server in a container, on the standard library alone.",
               "files": {"main.py": _SERVER, "requirements.txt": "", "Procfile": "web: python main.py\n"}},
}


def files_of(template: str, name: str) -> Dict[str, str]:
    """``template``'s files for an app called ``name``."""
    return {path: str(text).replace("{name}", name).replace("{{", "{").replace("}}", "}")
            for path, text in TEMPLATES[template]["files"].items()}  # type: ignore[union-attr]
