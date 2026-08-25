"""
HTML building blocks for system notification emails (utils/notifications.py).

Light-theme, table-based, fully inline-styled — built for email clients (no
flexbox, no external CSS, Outlook-friendly nested tables). The shell mirrors
the email unsubscribe confirmation page (black header bar, white card on a
#f4f4f5 page) so every NoClick system surface reads the same. Components:
key-value detail tables, error panels, progress bars, stat tiles, and the
7-day activity / per-workflow bar charts the weekly digest uses.
"""

from datetime import datetime

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

INK = "#18181b"        # primary text / bars / CTA
BODY = "#3f3f46"       # body copy
MUTED = "#71717a"      # secondary
FAINT = "#a1a1aa"      # labels
HAIRLINE = "#f1f1f3"
RED = "#dc2626"
AMBER = "#d97706"


def build_email_shell(
    *,
    preheader: str,
    blocks_html: str,
    frontend_url: str,
    heading: str = "",
    eyebrow: str = "",
    badge_html: str = "",
    cta_text: str = "",
    cta_url: str = "",
    postscript_html: str = "",
    footer_html: str = "",
    title: str = "NoClick",
) -> str:
    """THE email shell — every NoClick email (system alerts, workspace
    invites, credential requests, the send-email node) renders through this
    one function, so a styling change here updates them all.

    Optional pieces render only when provided: badge (e.g. an org avatar),
    eyebrow label, heading, CTA button, postscript (small print under the
    CTA, inside the card), and the middle footer line (defaults to just
    "Sent from NoClick"). No dark bands by design: under forced dark mode,
    background and text invert TOGETHER, which is the safe case —
    black-banded layouts are what email clients recolor inconsistently.
    """
    eyebrow_html = (
        f'<p style="margin:0 0 10px;font-size:11px;font-weight:600;letter-spacing:0.08em;'
        f'text-transform:uppercase;color:{FAINT};font-family:{FONT};">{eyebrow}</p>'
        if eyebrow else ""
    )
    heading_html = (
        f'<h1 style="margin:0 0 18px;font-size:21px;font-weight:600;letter-spacing:-0.3px;'
        f'color:{INK};font-family:{FONT};">{heading}</h1>'
        if heading else ""
    )
    badge_block = f'<div style="margin:0 0 16px;">{badge_html}</div>' if badge_html else ""
    cta_html = (
        '<table role="presentation" cellspacing="0" cellpadding="0" style="margin-top:26px;">'
        f'<tr><td style="background-color:{INK};border-radius:9px;">'
        f'<a href="{cta_url}" style="display:inline-block;padding:11px 24px;font-size:14px;'
        f'font-weight:600;color:#ffffff;text-decoration:none;font-family:{FONT};">{cta_text}</a>'
        "</td></tr></table>"
        if cta_text and cta_url else ""
    )
    footer_line = footer_html or f'Sent from <a href="{frontend_url}" style="color:{MUTED};">NoClick</a>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f5;font-family:{FONT};">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">{preheader}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f5;">
<tr><td align="center" style="padding:32px 16px 40px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;">
  <tr><td style="padding:0 2px 14px;">
    <a href="{frontend_url}/dashboard" style="text-decoration:none;">
      <span style="color:{INK};font-size:15px;font-weight:600;letter-spacing:-0.2px;vertical-align:middle;font-family:{FONT};">NoClick</span>
    </a>
  </td></tr>
  <tr><td style="background-color:#ffffff;border:1px solid #e4e4e7;border-radius:14px;padding:30px 32px 32px;">
    {badge_block}{eyebrow_html}{heading_html}{blocks_html}{cta_html}{postscript_html}
  </td></tr>
  <tr><td align="center" style="padding:22px 8px 0;">
    <p style="margin:0 0 6px;font-size:12px;line-height:1.7;color:{FAINT};font-family:{FONT};">
      {footer_line}
    </p>
    <p style="margin:0;font-size:12px;color:#c5c5cc;font-family:{FONT};">&copy; {datetime.now().year} NoClick</p>
  </td></tr>
</table>
</td></tr></table>
</body>
</html>"""


def build_alert_html(
    *,
    preheader: str,
    eyebrow: str,
    heading: str,
    blocks_html: str,
    cta_text: str,
    cta_url: str,
    unsubscribe_url: str,
    unsubscribe_label: str,
    frontend_url: str,
) -> str:
    """System-alert variant of the shell: standard unsubscribe footer."""
    return build_email_shell(
        preheader=preheader,
        eyebrow=eyebrow,
        heading=heading,
        blocks_html=blocks_html,
        cta_text=cta_text,
        cta_url=cta_url,
        frontend_url=frontend_url,
        title=heading,
        footer_html=(
            f'Sent from <a href="{frontend_url}" style="color:{MUTED};">NoClick</a>'
            "&nbsp;&middot;&nbsp;"
            f'<a href="{unsubscribe_url}" style="color:{MUTED};">Unsubscribe from {unsubscribe_label}</a>'
        ),
    )


def para(html: str) -> str:
    return f'<p style="margin:0 0 14px;font-size:14px;line-height:1.65;color:{BODY};font-family:{FONT};">{html}</p>'


def strong(html: str) -> str:
    return f'<strong style="color:{INK};font-weight:600;">{html}</strong>'


def kv_rows(rows) -> str:
    """Key-value detail table. rows: [(label, value_html)] — values pre-escaped."""
    trs = ""
    for i, (label, value) in enumerate(rows):
        border = f"border-top:1px solid {HAIRLINE};" if i else ""
        trs += (
            f'<tr><td style="{border}padding:8px 16px 8px 0;font-size:13px;color:{MUTED};'
            f'white-space:nowrap;vertical-align:top;font-family:{FONT};">{label}</td>'
            f'<td style="{border}padding:8px 0;font-size:13px;color:{INK};font-weight:500;'
            f'font-family:{FONT};word-break:break-word;">{value}</td></tr>'
        )
    return (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'style="margin:2px 0 16px;">{trs}</table>'
    )


def error_panel(error_html: str) -> str:
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 16px;"><tr>'
        f'<td style="background-color:#fef2f2;border:1px solid #fee2e2;border-radius:9px;padding:12px 14px;'
        f'font-family:{MONO};font-size:12px;line-height:1.6;color:#b91c1c;word-break:break-word;">'
        f"{error_html}</td></tr></table>"
    )


def progress_bar(pct: float, label_left: str, label_right: str, fill: str = INK) -> str:
    pct_i = max(0, min(100, int(round(pct))))
    filled = (
        f'<td width="{pct_i}%" style="background-color:{fill};border-radius:5px;height:8px;'
        'font-size:0;line-height:0;">&nbsp;</td>'
        if pct_i > 0 else ""
    )
    rest = (
        '<td style="height:8px;font-size:0;line-height:0;">&nbsp;</td>'
        if pct_i < 100 else ""
    )
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:2px 0 16px;">'
        f'<tr><td style="font-size:12px;color:{MUTED};padding-bottom:7px;font-family:{FONT};">{label_left}</td>'
        f'<td align="right" style="font-size:12px;color:{MUTED};padding-bottom:7px;font-family:{FONT};">{label_right}</td></tr>'
        f'<tr><td colspan="2"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'style="background-color:{HAIRLINE};border-radius:5px;"><tr>{filled}{rest}</tr></table></td></tr>'
        "</table>"
    )


def stat_tiles(stats) -> str:
    """Row of big-number tiles. stats: [(value, label)] — typically 3."""
    cells = []
    for value, label in stats:
        cells.append(
            f'<td align="center" style="background-color:#fafafa;border-radius:11px;padding:16px 6px 14px;">'
            f'<div style="font-size:24px;font-weight:650;letter-spacing:-0.5px;color:{INK};font-family:{FONT};">{value}</div>'
            f'<div style="font-size:10px;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;'
            f'color:{FAINT};padding-top:5px;font-family:{FONT};">{label}</div></td>'
        )
    spacer = '<td width="10" style="font-size:0;">&nbsp;</td>'
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:4px 0 20px;"><tr>'
        + spacer.join(cells)
        + "</tr></table>"
    )


def day_bars(day_counts) -> str:
    """7-day activity chart: vertical bars scaled to the busiest day.
    day_counts: [(day_label, count)] oldest → newest."""
    mx = max((c for _, c in day_counts), default=0) or 1
    count_row = bar_row = label_row = ""
    for label, count in day_counts:
        height = max(3, int(round(count / mx * 54))) if count else 3
        color = INK if count else "#e4e4e7"
        count_row += (
            f'<td align="center" style="font-size:11px;font-weight:600;color:{MUTED};'
            f'padding:0 3px 5px;font-family:{FONT};">{count or ""}</td>'
        )
        bar_row += (
            f'<td align="center" valign="bottom" style="padding:0 3px;">'
            f'<div style="width:100%;max-width:36px;height:{height}px;background-color:{color};'
            f'border-radius:4px 4px 2px 2px;font-size:0;line-height:0;margin:0 auto;">&nbsp;</div></td>'
        )
        label_row += (
            f'<td align="center" style="font-size:10px;color:{FAINT};padding:6px 3px 0;'
            f'font-family:{FONT};">{label}</td>'
        )
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:2px 0 20px;">'
        f"<tr>{count_row}</tr><tr>{bar_row}</tr><tr>{label_row}</tr></table>"
    )


def _bar_segments(parts) -> str:
    """Filled segments for a horizontal bar. parts: [(width_pct, color)] with
    zero-width parts already filtered. The fill's outer corners get the same
    radius as the track so a partial fill reads as a rounded pill, not a
    square block inside rounded ends."""
    cells = ""
    last = len(parts) - 1
    total = 0
    for i, (width, color) in enumerate(parts):
        radius = ""
        if i == 0:
            radius += "border-top-left-radius:3px;border-bottom-left-radius:3px;"
        if i == last:
            radius += "border-top-right-radius:3px;border-bottom-right-radius:3px;"
        cells += (
            f'<td width="{width}%" style="background-color:{color};{radius}height:6px;'
            'font-size:0;line-height:0;">&nbsp;</td>'
        )
        total += width
    if total < 100:
        cells += '<td style="height:6px;font-size:0;line-height:0;">&nbsp;</td>'
    return cells


def _labeled_bar(label_html: str, value_html: str, segments: str) -> str:
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 12px;">'
        f'<tr><td style="font-size:13px;font-weight:500;color:{INK};padding-bottom:5px;font-family:{FONT};">{label_html}</td>'
        f'<td align="right" style="font-size:12px;color:{MUTED};padding-bottom:5px;white-space:nowrap;font-family:{FONT};">{value_html}</td></tr>'
        '<tr><td colspan="2"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'style="background-color:{HAIRLINE};border-radius:3px;"><tr>{segments}</tr></table></td></tr>'
        "</table>"
    )


def workflow_bars(rows) -> str:
    """Per-workflow run bars, width relative to the busiest workflow, split
    dark (succeeded) / red (failed). rows: [(name_escaped, runs, failures)]."""
    mx = max((r[1] for r in rows), default=0) or 1
    out = ""
    for name, runs, failures in rows:
        width = max(6, int(round(runs / mx * 100)))
        fail_w = int(round(width * failures / runs)) if runs else 0
        ok_w = width - fail_w
        parts = [(w, c) for w, c in ((ok_w, INK), (fail_w, RED)) if w > 0]
        counts = f"{runs} run{'s' if runs != 1 else ''}"
        if failures:
            counts += f' &middot; <span style="color:{RED};">{failures} failed</span>'
        out += _labeled_bar(name, counts, _bar_segments(parts))
    return out


def credit_bars(rows) -> str:
    """Per-consumer credit bars, width relative to the biggest spender.
    rows: [(name_escaped, credits_float)]."""
    mx = max((r[1] for r in rows), default=0.0) or 1.0
    out = ""
    for name, credits in rows:
        width = max(6, int(round(credits / mx * 100)))
        out += _labeled_bar(name, f"{credits:.1f} cr", _bar_segments([(width, INK)]))
    return out


def section_label(text: str) -> str:
    return (
        f'<p style="margin:6px 0 12px;font-size:11px;font-weight:600;letter-spacing:0.07em;'
        f'text-transform:uppercase;color:{FAINT};font-family:{FONT};">{text}</p>'
    )
