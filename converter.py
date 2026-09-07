"""
converter.py — assemble a cleaned Article into an A4 PDF.

This is the shared engine. Both the command-line tool and the local web app
call `convert()`; nothing else should need to know about WeasyPrint.
"""

from __future__ import annotations

import html as html_lib
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from datetime import date

# Must run before weasyprint is imported: it fixes the macOS library search path
# and may re-exec the process to do so.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: E402

_bootstrap.ensure_native_libs()

try:
    from weasyprint import HTML, CSS
except OSError as exc:  # native libraries missing or unreachable
    raise SystemExit(
        f"\nWeasyPrint could not load its native libraries.\n  {exc}\n\n"
        "Run this for a diagnosis and the exact fix:\n"
        "    python3 html2pdf.py --doctor\n"
    ) from exc

import extractor  # noqa: E402
from extractor import Article  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STYLE_DIR = os.path.join(HERE, "styles")

# A4 text block with the 25mm margins set in essay.css. The extractor uses these
# to guarantee no image is ever taller than one page.
TEXT_WIDTH_MM = 160.0
TEXT_HEIGHT_MM = 195.0


@dataclass
class Result:
    pdf_path: str
    title: str
    word_count: int
    images: int
    pages: int
    warnings: list[str]


def _esc(text: str) -> str:
    return html_lib.escape(text or "", quote=True)


def _build_document(art: Article, *, numbered: bool, show_url: bool,
                    standfirst: bool) -> str:
    """Wrap the cleaned body in the title block, endnotes and colophon."""

    meta_bits = []
    if art.byline:
        meta_bits.append(f'<span class="w2p-byline">{_esc(art.byline)}</span>')
    if art.site:
        meta_bits.append(_esc(art.site))
    if art.published:
        meta_bits.append(_esc(art.published))

    meta_line = '<span class="w2p-sep">·</span>'.join(meta_bits)

    url_line = ""
    if show_url and art.source_url:
        url_line = f'<div class="w2p-url">{_esc(art.source_url)}</div>'

    stand = ""
    if standfirst and art.excerpt and len(art.excerpt) > 60:
        # Don't repeat the opening sentence if the excerpt is just a snippet of it.
        opening = re.sub(r"\W+", "", art.body_html[:400]).lower()
        if re.sub(r"\W+", "", art.excerpt[:60]).lower() not in opening:
            stand = f'<p class="w2p-standfirst">{_esc(art.excerpt.rstrip("… ."))}.</p>'

    endnotes_html = ""
    if art.endnotes:
        items = "\n".join(
            f'<li>{_esc(text[:110])} — <span class="w2p-note-url">{_esc(url)}</span></li>'
            for text, url in art.endnotes
        )
        endnotes_html = (
            f'<section class="w2p-endnotes"><h2>Links in this article</h2>'
            f"<ol>{items}</ol></section>"
        )

    origin = art.source_url or art.site or "a local file"
    colophon = (
        f'<div class="w2p-colophon">Reformatted for A4 print from {_esc(origin)} '
        f'· {art.word_count:,} words · prepared {date.today():%d %B %Y}</div>'
    )

    body_class = "w2p-numbered" if numbered else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{_esc(art.title)}</title></head>
<body class="{body_class}">
<header class="w2p-titleblock">
  <h1>{_esc(art.title)}</h1>
  <div class="w2p-meta">{meta_line}{url_line}</div>
  {stand}
</header>
<main>
{art.body_html}
</main>
{endnotes_html}
{colophon}
</body>
</html>"""


def convert(source: str, output_path: str, *,
            style: str = "essay",
            numbered: bool = True,
            link_mode: str = "plain",
            show_url: bool = True,
            standfirst: bool = True,
            images: bool = True,
            keep_html: str | None = None,
            timeout: int = 30) -> Result:
    """
    Convert a URL or local .html file into an A4 PDF.

    `source` may be an http(s) URL or a filesystem path.
    Returns a Result describing what was produced.
    """
    asset_dir = tempfile.mkdtemp(prefix="w2p-assets-")
    try:
        if source.startswith(("http://", "https://")):
            raw_html, base_url = extractor.fetch(source, timeout=timeout)
        else:
            path = os.path.abspath(os.path.expanduser(source))
            if not os.path.isfile(path):
                raise FileNotFoundError(f"No such file: {path}")
            raw_html, base_url = extractor.read_local(path)

        art = extractor.extract(
            raw_html, base_url, asset_dir,
            link_mode=link_mode,
            text_width_mm=TEXT_WIDTH_MM,
            text_height_mm=TEXT_HEIGHT_MM,
            download_images=images,
        )

        document_html = _build_document(
            art, numbered=numbered, show_url=show_url, standfirst=standfirst
        )

        if keep_html:
            with open(keep_html, "w", encoding="utf-8") as fh:
                fh.write(document_html)

        css_path = os.path.join(STYLE_DIR, f"{style}.css")
        if not os.path.isfile(css_path):
            raise FileNotFoundError(
                f"Unknown style '{style}'. Available: "
                + ", ".join(sorted(
                    f[:-4] for f in os.listdir(STYLE_DIR) if f.endswith(".css")
                ))
            )

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        doc = HTML(string=document_html, base_url=asset_dir + os.sep).render(
            stylesheets=[CSS(filename=css_path)]
        )
        doc.write_pdf(output_path)

        return Result(
            pdf_path=os.path.abspath(output_path),
            title=art.title,
            word_count=art.word_count,
            images=art.images,
            pages=len(doc.pages),
            warnings=art.warnings,
        )
    finally:
        shutil.rmtree(asset_dir, ignore_errors=True)


def suggest_filename(title: str, fallback: str = "document") -> str:
    """A tidy, filesystem-safe name derived from the article title."""
    name = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip()
    name = re.sub(r"[\s_]+", "-", name)
    name = name[:70].strip("-")
    return (name or fallback) + ".pdf"


def available_styles() -> list[str]:
    if not os.path.isdir(STYLE_DIR):
        return []
    return sorted(f[:-4] for f in os.listdir(STYLE_DIR) if f.endswith(".css"))
