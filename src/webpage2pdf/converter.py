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
from . import presets  # noqa: E402
from .extractor import Article  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STYLE_DIR = os.path.join(HERE, "styles")

# Page geometry now lives in presets.py, which emits the CSS and reports the
# text block from the same numbers, so the two can no longer drift apart. These
# names are kept because they are part of the module's surface, and they are
# what the default A4 preset resolves to.
TEXT_WIDTH_MM = presets.get(presets.DEFAULT_PRESET).text_width_mm     # 160.0
TEXT_HEIGHT_MM = presets.get(presets.DEFAULT_PRESET).text_height_mm   # 195.0


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


# A contents list earns its place once a document is long enough that you would
# otherwise scroll to find a section. Both conditions must hold: a 900-word piece
# with five subheadings does not need one, and neither does a 4000-word essay
# written as continuous prose.
TOC_MIN_SECTIONS = 4
TOC_MIN_WORDS = 1500


def _wants_toc(art: Article, toc: bool | None) -> bool:
    """`toc` is True/False to force, or None to decide from the document."""
    if toc is not None:
        return toc
    top_level = sum(1 for level, _, _ in art.sections if level == 2)
    return top_level >= TOC_MIN_SECTIONS and art.word_count >= TOC_MIN_WORDS


def _build_toc(art: Article) -> str:
    """
    A contents list with real page numbers.

    The page numbers are not computed here. Each entry carries a link to its
    heading and the stylesheet fills in the number with
    target-counter(attr(href), page), which CSS resolves after layout. That
    matters because inserting this list shifts every page number in the
    document — including its own — so anything computed in advance would be
    wrong by exactly the length of the contents list.
    """
    if not art.sections:
        return ""
    items = "\n".join(
        f'<li class="w2p-toc-l{level}"><a href="#{anchor}">{_esc(text)}</a></li>'
        for level, anchor, text in art.sections
    )
    return (
        '<nav class="w2p-toc">'
        '<h2 class="w2p-toc-head">Contents</h2>'
        f"<ol>{items}</ol></nav>"
    )


def _build_document(art: Article, *, numbered: bool, show_url: bool,
                    standfirst: bool, toc: bool = False) -> str:
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
    toc_html = _build_toc(art) if toc else ""

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
{toc_html}
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
            toc: bool | None = None,
            preset: str = presets.DEFAULT_PRESET,
            keep_html: str | None = None,
            timeout: int = 30) -> Result:
    """
    Convert a URL or local .html file into an A4 PDF.

    `source` may be an http(s) URL or a filesystem path.
    `toc` is True/False to force a contents list, or None to decide from the
    document's length and section count.
    `preset` names a page geometry from presets.PRESETS.
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

        page = presets.get(preset)

        art = extractor.extract(
            raw_html, base_url, asset_dir,
            link_mode=link_mode,
            # Fitted against this preset's text block, not A4's, so an image
            # that fits one page on A4 still fits one page on A5.
            text_width_mm=page.text_width_mm,
            text_height_mm=page.text_height_mm,
            download_images=images,
        )

        document_html = _build_document(
            art, numbered=numbered, show_url=show_url, standfirst=standfirst,
            toc=_wants_toc(art, toc),
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
            stylesheets=[
                CSS(filename=css_path, font_config=font_config),
                # Geometry last, so a preset overrides whatever @page the
                # chosen stylesheet declares.
                CSS(string=page.css(), font_config=font_config),
            ],
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
