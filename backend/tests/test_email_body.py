"""
Email body preparation (utils/email_body.py).

Contract under test:
- markdown / plain-text bodies render to an inline-styled HTML fragment
  (no <style> blocks — Gmail clips them, Outlook ignores them) with the
  raw body kept verbatim as the plain-text alternative;
- raw HTML inside a markdown body is escaped, never interpreted;
- structural HTML bodies pass through (document chrome unwrapped, scripts
  dropped) with a tag-stripped text alternative;
- HTML mentioned inside code fences/spans does not flip the mode;
- ensure_html_body (Gmail/Outlook mailbox sends, body = whole email) keeps
  HTML byte-identical and renders everything else so newlines survive
  text/html delivery.
"""

from utils.email_body import ensure_html_body, looks_like_html, prepare_email_body


class TestMarkdownMode:
    def test_renders_llm_markdown(self):
        body = (
            "### 📈 **Trending Stocks**\n\n"
            "1. **SMCI** — dropped **28%**\n"
            "   - heavy bagholder posts\n\n"
            "---\n\n"
            "> Sentiment: tense and inflation-wary.\n\n"
            "| Ticker | Move |\n|---|---:|\n| SMCI | -28% |"
        )
        html, text = prepare_email_body(body)
        assert text == body  # markdown source IS the text alternative
        for tag in ("<h3", "<ol", "<ul", "<hr", "<blockquote", "<table", "<strong>"):
            assert tag in html
        assert "###" not in html and "**" not in html

    def test_every_element_styled_inline(self):
        html, _ = prepare_email_body("# T\n\npara\n\n- li\n\n| a |\n|---|\n| b |")
        for tag in ("h1", "p", "ul", "li", "table", "th", "td"):
            assert f'<{tag} style="' in html

    def test_table_alignment_wins_over_base_style(self):
        html, _ = prepare_email_body("| a |\n|---:|\n| b |")
        # markdown-it's alignment is appended after the base style so it wins.
        assert "text-align:left;text-align:right" in html

    def test_plain_text_newlines_become_br(self):
        html, text = prepare_email_body("line1\nline2")
        assert "line1<br>" in html
        assert text == "line1\nline2"

    def test_raw_html_in_markdown_is_escaped(self):
        html, _ = prepare_email_body("hello <script>alert(1)</script> world")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_intraword_chars_safe(self):
        html, _ = prepare_email_body("#1 priority: ship & iterate")
        assert "<h1" not in html  # '#1' is not a heading
        assert "&amp;" in html

    def test_code_fence_with_html_stays_markdown(self):
        body = "Here is the snippet:\n\n```html\n<div class=\"x\">hi</div>\n```"
        assert not looks_like_html(body)
        html, _ = prepare_email_body(body)
        assert "&lt;div" in html and "<div class=" not in html

    def test_inline_code_with_html_stays_markdown(self):
        assert not looks_like_html("wrap it in a `<div>` element")


class TestHtmlMode:
    def test_fragment_passes_through(self):
        body = "<p>Hello <strong>world</strong></p><p>Bye</p>"
        html, text = prepare_email_body(body)
        assert html == body
        assert text == "Hello world\nBye"

    def test_document_chrome_unwrapped(self):
        body = (
            "<!DOCTYPE html><html><head><style>p{color:red}</style></head>"
            "<body><h2>Report</h2><p>All good.</p></body></html>"
        )
        html, text = prepare_email_body(body)
        assert "<h2>Report</h2>" in html
        assert "DOCTYPE" not in html and "<head" not in html and "<body" not in html
        assert text == "Report\nAll good."

    def test_scripts_dropped(self):
        html, text = prepare_email_body("<p>hi</p><script>alert(1)</script>")
        assert "<script" not in html and "alert" not in html
        assert text == "hi"

    def test_entities_unescaped_in_text_alternative(self):
        _, text = prepare_email_body("<p>Tom &amp; Jerry</p>")
        assert text == "Tom & Jerry"


class TestEnsureHtmlBody:
    def test_plain_text_newlines_survive(self):
        html = ensure_html_body("line1\nline2\n\nline3")
        assert "line1<br>" in html
        assert "<p" in html  # blank line starts a new paragraph

    def test_markdown_renders(self):
        html = ensure_html_body("**bold** and a list:\n- one\n- two")
        assert "<strong>bold</strong>" in html and "<li" in html

    def test_html_passes_through_byte_identical(self):
        # Unlike prepare_email_body, no fragment extraction: a full HTML
        # document is a valid whole-email body and must not be rewritten.
        body = "<!DOCTYPE html><html><body><p>Hi\nthere</p></body></html>"
        assert ensure_html_body(body) == body

    def test_empty_body_stays_empty(self):
        assert ensure_html_body("") == ""
