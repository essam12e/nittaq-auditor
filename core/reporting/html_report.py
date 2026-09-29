"""Standalone RTL HTML rendering of an Arabic report (Tajawal font embedded)."""

from __future__ import annotations

import base64
import html
from pathlib import Path

from core.reporting.guard import check_text

FONT = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Tajawal-Medium.ttf"

_CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#5d5d58;--card:#fff;--line:#e3e3de}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ececea;--muted:#a3a39d;--card:#1e1e1c;--line:#33332f}}
@font-face{font-family:Tajawal;src:url(data:font/ttf;base64,__FONT__) format('truetype');font-weight:500}
body{margin:0;background:var(--bg);color:var(--fg);font-family:Tajawal,system-ui,sans-serif;line-height:1.8}
main{max-width:860px;margin:0 auto;padding:24px 16px}
h1{font-size:1.6rem;margin:0 0 12px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:14px 0}
p{margin:2px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.muted{color:var(--muted)}
code{font-family:ui-monospace,monospace;direction:ltr;unicode-bidi:embed}
"""


def render_html(report_text: str, title: str = "تقرير مدقق نطاق") -> str:
    check_text(report_text)
    font_b64 = base64.b64encode(FONT.read_bytes()).decode() if FONT.exists() else ""
    css = _CSS.replace("__FONT__", font_b64)
    blocks = [b for b in report_text.split("\n\n") if b.strip()]
    body = [f"<h1>{html.escape(title)}</h1>"]
    for b in blocks:
        lines = b.split("\n")
        if lines[0].strip() == title:
            lines = lines[1:]
        paras = "".join(
            ('<p class="muted">' if ln.startswith(("•", "   ")) else "<p>") + html.escape(ln) + "</p>"
            for ln in lines
            if ln.strip()
        )
        if paras:
            body.append(f"<section>{paras}</section>")
    return (
        "<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{css}</style></head><body><main>"
        + "".join(body)
        + "</main></body></html>"
    )
