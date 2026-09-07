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
import tempfile
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import date

# Must run before weasyprint is imported: it fixes the macOS library search path
# and may re-exec the process to do so. Installed via Homebrew this is a no-op,
# because the formula links the native libraries where dyld already looks.
from . import _bootstrap  # noqa: E402

_bootstrap.ensure_native_libs()

try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
except OSError as exc:  # native libraries missing or unreachable
    raise SystemExit(
        f"\nWeasyPrint could not load its native libraries.\n  {exc}\n\n"
        "Run this for a diagnosis and the exact fix:\n"
        "    webpage2pdf --doctor\n"
    ) from exc

from . import extractor  # noqa: E402
from .extractor import Article  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STYLE_DIR = os.path.join(HERE, "styles")

# The box an image must fit inside, in millimetres.
#
# TEXT_WIDTH_MM is the real text measure: A4 is 210mm wide and essay.css sets
# 25mm side margins, so 210 - 25 - 25 = 160.
#
# TEXT_HEIGHT_MM is deliberately NOT the full text block. That block is
# 297 - 25 (top) - 22 (bottom) = 250mm, but an image is never alone on the page:
# it carries a caption, and a figure is atomic (break-inside: avoid), so a
# 250mm-tall image plus a caption produces a figure taller than any page can
# hold — which forces exactly the split this tool exists to prevent. The 55mm of
# slack is headroom for the caption and a line or two of surrounding text.
#
# If you change the margins in essay.css, change TEXT_WIDTH_MM to match the new
# measure, but keep the slack in TEXT_HEIGHT_MM rather than setting it to the
# full block height.
PAGE_HEIGHT_MM = 297.0          # A4
MARGIN_TOP_MM = 25.0            # must match @page in essay.css
MARGIN_BOTTOM_MM = 22.0         # must match @page in essay.css
CAPTION_HEADROOM_MM = 55.0      # room for a caption under a full-height image

TEXT_WIDTH_MM = 160.0
TEXT_HEIGHT_MM = (
    PAGE_HEIGHT_MM - MARGIN_TOP_MM - MARGIN_BOTTOM_MM - CAPTION_HEADROOM_MM
)


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

    # WeasyPrint maps these straight onto PDF document metadata: author, subject,
    # keywords and creation date. Without them the PDF lands in a library or a
    # reference manager with an empty Author field, even though we parsed one.
    meta_tags = ['<meta charset="utf-8">']
    if art.byline:
        meta_tags.append(f'<meta name="author" content="{_esc(art.byline)}">')
    if art.excerpt:
        meta_tags.append(f'<meta name="description" content="{_esc(art.excerpt[:300])}">')
    if art.site:
        meta_tags.append(f'<meta name="keywords" content="{_esc(art.site)}">')
    meta_tags.append(
        f'<meta name="dcterms.created" content="{date.today():%Y-%m-%d}">'
    )
    head = "".join(meta_tags)

    # lang drives hyphenation: WeasyPrint selects its dictionary from this
    # attribute, so a wrong value hyphenates the text with another language's
    # patterns. See extractor._extract_lang.
    return f"""<!DOCTYPE html>
<html lang="{_esc(art.lang or 'en')}">
<head>{head}<title>{_esc(art.title)}</title></head>
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

        # One FontConfiguration, shared by the stylesheet and the render.
        #
        # This is not optional bookkeeping. @font-face rules are collected into
        # the FontConfiguration when the stylesheet is parsed and read back when
        # the document is laid out. Pass it to only one of the two — or, as this
        # did before, to neither — and every @font-face is parsed, silently
        # discarded, and the text falls back to whatever fontconfig considers
        # the closest match. There is no warning: the PDF renders happily in the
        # wrong typeface. On this machine an unknown family resolves to Verdana,
        # so a bundled serif would have come out as a system sans.
        font_config = FontConfiguration()

        doc = HTML(string=document_html, base_url=asset_dir + os.sep).render(
            stylesheets=[CSS(filename=css_path, font_config=font_config)],
            font_config=font_config,
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


def staging_path(directory: str) -> str:
    """
    A scratch path to render into before the article title is known.

    Unique per process *and* per thread: the CLI can be run twice against the
    same -d directory, and server.py is a ThreadingMixIn server that handles
    concurrent requests, so a single fixed name means one conversion silently
    overwrites another's half-written file.
    """
    return os.path.join(
        directory, f".w2p-staging-{os.getpid()}-{threading.get_ident():x}.pdf"
    )


def claim_output_path(preferred: str) -> str:
    """
    Reserve `preferred`, or the next free `name-2.pdf`, `name-3.pdf`, …

    Atomic on purpose. The obvious version —

        if os.path.exists(final):
            ... find a free suffix ...
        os.replace(tmp, final)

    is a time-of-check/time-of-use race: two conversions finishing together both
    see the name as free and both rename onto it, so one result vanishes. Here
    the name is claimed with O_CREAT|O_EXCL, which either succeeds for exactly
    one caller or raises, and the caller then renames over its own placeholder.
    """
    stem, ext = os.path.splitext(preferred)
    for n in range(1, 1000):
        candidate = preferred if n == 1 else f"{stem}-{n}{ext}"
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate
    # Nearly a thousand documents share this title; stop being clever.
    raise FileExistsError(f"Could not find a free filename near {preferred}")


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
