"""
Email body preparation — HTML autodetect + markdown rendering.

LLM/user-authored email bodies arrive in three shapes: ready-made HTML,
markdown, or plain text. Wrapped outbound surfaces (nodes/send_email_node.py
and the agent's email__reply tool) route their body through
prepare_email_body(): structural HTML passes through as-is; everything else
renders as markdown. Mailbox nodes (Gmail/Outlook), where the body IS the
whole email, use ensure_html_body() instead.

Deliverability constraints drive the rendering choices:
- every element carries inline styles (Gmail clips/strips <style> blocks,
  Outlook ignores them — inline CSS is the only reliable styling in email);
- the plain-text alternative mirrors the HTML part (markdown source, or
  tag-stripped text for an HTML body) so multipart content stays consistent
  for spam filters;
- raw HTML inside a markdown body is escaped (html=False), never interpreted.
"""

import html as html_lib
import re
from functools import lru_cache
from typing import Tuple

# Block/structural tags only: their presence means the author wrote HTML, not
# markdown. Pure-inline tags (b/i/em/strong) are deliberately excluded — prose
# *mentioning* them shouldn't flip the whole body out of markdown mode.
_STRUCTURAL_TAG_RE = re.compile(
    r"(?i)</?(?:html|head|body|div|p|br|hr|table|thead|tbody|tr|td|th|h[1-6]"
    r"|ul|ol|li|blockquote|pre|a|img|span|section|article|center|font)\b[^>]*/?>"
)
_CODE_RE = re.compile(r"(?s)```.*?```|`[^`\n]*`")

_MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
_BORDER = "1px solid #e4e4e7"
_BLOCK_CODE_STYLE = (
    f"display:block;background-color:#f4f4f5;padding:12px 14px;border-radius:6px;"
    f"font-family:{_MONO};font-size:13px;line-height:1.5;white-space:pre-wrap;"
    f"margin:0 0 14px"
)

# Keyed by token type where one tag renders differently per context (fenced
# code block vs inline code span), else by tag.
_TYPE_STYLES = {
    "fence": _BLOCK_CODE_STYLE,
    "code_block": _BLOCK_CODE_STYLE,
    "code_inline": (
        f"font-family:{_MONO};font-size:13px;background-color:#f4f4f5;"
        f"padding:1px 5px;border-radius:4px"
    ),
}
_TAG_STYLES = {
    "h1": "margin:24px 0 12px;font-size:21px;line-height:1.3;font-weight:700",
    "h2": "margin:22px 0 10px;font-size:18px;line-height:1.35;font-weight:700",
    "h3": "margin:20px 0 8px;font-size:16px;line-height:1.4;font-weight:700",
    "h4": "margin:18px 0 8px;font-size:15px;line-height:1.4;font-weight:700",
    "h5": "margin:16px 0 8px;font-size:14px;line-height:1.4;font-weight:700",
    "h6": "margin:16px 0 8px;font-size:13px;line-height:1.4;font-weight:700",
    "p": "margin:0 0 14px",
    "ul": "margin:0 0 14px;padding-left:24px",
    "ol": "margin:0 0 14px;padding-left:24px",
    "li": "margin:4px 0",
    "blockquote": (
        "margin:0 0 14px;padding:2px 0 2px 14px;"
        f"border-left:3px solid #e4e4e7;color:#52525b"
    ),
    "hr": f"border:none;border-top:{_BORDER};margin:20px 0",
    "a": "color:#2563eb",
    "table": "border-collapse:collapse;margin:0 0 14px;font-size:14px",
    "th": (
        f"border:{_BORDER};padding:6px 10px;background-color:#fafafa;"
        "font-weight:600;text-align:left"
    ),
    "td": f"border:{_BORDER};padding:6px 10px",
    "img": "max-width:100%",
}


@lru_cache(maxsize=1)
def _markdown():
    from markdown_it import MarkdownIt

    # js-default: html=False (raw HTML escaped), tables + strikethrough on.
    # breaks=True keeps plain-text bodies rendering newlines as <br>.
    return MarkdownIt("js-default", {"breaks": True})


def _style_tokens(tokens) -> None:
    """Attach inline styles to every opening/self-closing token, recursively.

    Existing style attrs (markdown-it emits text-align for aligned table
    columns) are appended after ours so they win.
    """
    for tok in tokens:
        if tok.children:
            _style_tokens(tok.children)
        if tok.nesting == -1:
            continue
        style = _TYPE_STYLES.get(tok.type) or _TAG_STYLES.get(tok.tag)
        if not style:
            continue
        existing = tok.attrGet("style")
        tok.attrSet("style", f"{style};{existing}" if existing else style)


def render_markdown_email(body: str) -> str:
    """Markdown (or plain text) → an inline-styled HTML fragment."""
    md = _markdown()
    tokens = md.parse(body)
    _style_tokens(tokens)
    return md.renderer.render(tokens, md.options, {})


def looks_like_html(body: str) -> bool:
    """True when the body contains structural HTML outside code fences/spans."""
    return bool(_STRUCTURAL_TAG_RE.search(_CODE_RE.sub("", body)))


def _extract_fragment(body: str) -> str:
    """An author-supplied HTML document/fragment, ready to embed in a wrapper:
    document chrome unwrapped, scripts dropped (email clients strip them
    anyway — removing them just keeps the payload clean for spam filters)."""
    html = re.sub(r"(?is)<!doctype[^>]*>", "", body)
    # HTML parsers tolerate attributes and other parse-error text on end tags.
    # Consume the entire end tag rather than accepting only whitespace so a
    # payload such as ``</script\t ignored>`` cannot evade fragment cleanup.
    html = re.sub(r"(?is)<script\b[^>]*>.*?</script\b[^>]*>", "", html)
    html = re.sub(r"(?is)<head\b[^>]*>.*?</head\b[^>]*>", "", html)
    html = re.sub(r"(?is)</?(?:html|body)\b[^>]*>", "", html)
    return html.strip()


def _html_to_text(fragment: str) -> str:
    """Tag-stripped plain-text alternative for an HTML body."""
    text = re.sub(r"(?is)<style\b[^>]*>.*?</style>", "", fragment)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|h[1-6]|li|tr|table|blockquote|pre)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def prepare_email_body(body: str) -> Tuple[str, str]:
    """(html_fragment, text_alternative) for an LLM/user-authored body."""
    if looks_like_html(body):
        fragment = _extract_fragment(body)
        return fragment, _html_to_text(fragment)
    return render_markdown_email(body), body


def ensure_html_body(body: str) -> str:
    """A user-authored body about to be sent as text/html (Gmail/Outlook
    mailbox sends): structural HTML passes through untouched — no fragment
    extraction, the body is the whole email — while markdown/plain text
    renders to inline-styled HTML so newlines survive HTML rendering."""
    return body if looks_like_html(body) else render_markdown_email(body)
