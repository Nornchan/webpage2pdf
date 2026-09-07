"""
writers.py — turn a cleaned Article into something other than a PDF.

The extractor rebuilds every page into the same small, closed set of semantic
tags: p, h2-h4, ul/ol/li, blockquote, pre/code, figure/figcaption/img, table,
strong/em/sup/a/hr. That normalisation is what makes these writers short. They
are not general HTML converters and do not need to be — they only ever see
markup this project produced.

PDF is not here; it lives in converter, which owns WeasyPrint.
"""

from __future__ import annotations

import base64
import html as html_lib
import io
import mimetypes
import os
import re
import textwrap
import urllib.parse
import uuid
import zipfile
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup, NavigableString, Tag

from .extractor import Article

FORMATS = ("pdf", "html", "epub", "md")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def _local_path(src: str) -> str | None:
    """The extractor rewrites every kept image to a file:// URL in its asset dir."""
    if not src or not src.startswith("file://"):
        return None
    path = urllib.parse.unquote(urllib.parse.urlparse(src).path)
    return path if os.path.isfile(path) else None


def _data_uri(path: str) -> str | None:
    mime, _ = mimetypes.guess_type(path)
    if mime is None:
        mime = "application/octet-stream"
    try:
        with open(path, "rb") as fh:
            payload = base64.b64encode(fh.read()).decode("ascii")
    except OSError:
        return None
    return f"data:{mime};base64,{payload}"


def _subset_font(path: str, text: str) -> bytes | None:
    """
    Cut a font down to the characters this document actually uses.

    WeasyPrint does this automatically when it embeds a font in a PDF, which is
    why the PDFs are 20-50KB while the four full cuts are a megabyte. A
    standalone HTML file gets no such help, so we do it here: embedding the
    whole face would make a 3000-word article a 1.4MB download, almost all of
    it glyphs for languages the article is not written in.
    """
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return None

    try:
        font = TTFont(path, lazy=True)
        options = subset.Options()
        options.layout_features = ["*"]      # keep kerning, ligatures, onum, smcp
        options.notdef_outline = True
        options.recalc_bounds = False
        options.drop_tables = []
        options.flavor = "woff2"             # ~30% smaller again than raw TTF
        subsetter = subset.Subsetter(options=options)
        # Include the ASCII range whatever the text uses, so a viewer editing
        # the file by hand does not immediately hit missing glyphs.
        subsetter.populate(text=text + "".join(chr(c) for c in range(32, 127)))
        subsetter.subset(font)
        buffer = io.BytesIO()
        font.save(buffer)
        font.close()
        return buffer.getvalue()
    except Exception:
        return None       # fall back to embedding the full face


def _font_face_css(style_dir: str, text: str = "") -> str:
    """
    Re-declare the bundled face with the font files embedded as data URIs.

    A standalone HTML file has nowhere to resolve a relative font URL to, so
    without this the document falls back to system fonts and stops looking like
    the PDF. Each cut is subset to the characters actually used first.
    """
    font_dir = os.path.join(style_dir, "fonts")
    cuts = [
        ("Literata-Regular.ttf", 400, "normal"),
        ("Literata-Semibold.ttf", 600, "normal"),
        ("Literata-Italic.ttf", 400, "italic"),
        ("Literata-SemiboldItalic.ttf", 600, "italic"),
    ]
    out = []
    for filename, weight, style in cuts:
        path = os.path.join(font_dir, filename)
        if not os.path.isfile(path):
            continue

        payload = _subset_font(path, text) if text else None
        if payload is not None:
            encoded = base64.b64encode(payload).decode("ascii")
            uri = f"data:font/woff2;base64,{encoded}"
            fmt = "woff2"
        else:
            uri = _data_uri(path)
            fmt = "truetype"
            if uri is None:
                continue

        out.append(
            "@font-face {\n"
            '    font-family: "Literata";\n'
            f"    font-weight: {weight};\n"
            f"    font-style: {style};\n"
            f'    src: url("{uri}") format("{fmt}");\n'
            "}"
        )
    return "\n".join(out)


def _strip_font_faces(css: str) -> str:
    """Drop the stylesheet's own @font-face rules; they point at relative paths."""
    return re.sub(r"@font-face\s*\{[^}]*\}", "", css)


# --------------------------------------------------------------------------
# Standalone HTML
# --------------------------------------------------------------------------

SCREEN_CSS = """
/* Screen adjustments. The print stylesheet targets a fixed 160mm measure; a
   browser window is any width, so cap the line length instead — the same
   65-75 character target, expressed for a medium that has no page. */
html { font-size: 18px; }
body {
    margin: 0 auto;
    padding: 4rem 1.5rem 6rem;
    max-width: 38rem;
    background: #fbfaf8;
}
main, header, nav, .w2p-colophon, .w2p-endnotes { max-width: none; }
figure img { max-height: none; }
a { color: #2f3f52; }

@media (prefers-color-scheme: dark) {
    body { background: #16181c; color: #dfe1e4; }
    h1, h2, h3, h4 { color: #b9c6d8; }
    blockquote, .w2p-standfirst { color: #a9adb4; }
    th { background: #23262c; color: #b9c6d8; }
    pre, code { background: #21242a; }
}

/* The paged furniture has no meaning in a browser. */
@page { margin: 18mm; }
"""


def write_html(art: Article, document_html: str, css_text: str,
               output_path: str, *, style_dir: str,
               embed_fonts: bool = True) -> None:
    """
    One self-contained .html file: text, styles, fonts and images, no assets.

    This is the format closest to the source material, and the one worth
    reaching for when the fixed page is the wrong container — a long read on a
    phone, or something to keep in a notes folder and actually re-open.
    """
    soup = BeautifulSoup(document_html, "lxml")

    for img in soup.find_all("img"):
        path = _local_path(img.get("src", ""))
        if path is None:
            img.decompose()
            continue
        uri = _data_uri(path)
        if uri is None:
            img.decompose()
            continue
        img["src"] = uri
        img["loading"] = "lazy"
        # The print rule pins a millimetre width; on screen let it be fluid.
        if img.has_attr("style"):
            del img["style"]

    css = _strip_font_faces(css_text)
    if embed_fonts:
        css = _font_face_css(style_dir, soup.get_text(" ")) + "\n" + css

    head = soup.head or soup.new_tag("head")
    style = soup.new_tag("style")
    style.string = css + SCREEN_CSS
    head.append(style)

    viewport = soup.new_tag("meta")
    viewport.attrs = {"name": "viewport",
                      "content": "width=device-width, initial-scale=1"}
    head.append(viewport)

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html>\n" + str(soup))


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def _md_inline(node) -> str:
    """Render inline content. Only the tags the extractor emits are handled."""
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    if not isinstance(node, Tag):
        return ""

    inner = "".join(_md_inline(c) for c in node.children)

    if node.name in ("strong", "b"):
        return f"**{inner.strip()}**" if inner.strip() else ""
    if node.name in ("em", "i"):
        return f"*{inner.strip()}*" if inner.strip() else ""
    if node.name == "code":
        return f"`{inner.strip()}`"
    if node.name == "a" and node.get("href"):
        return f"[{inner.strip()}]({node['href']})"
    if node.name == "sup":
        return f"[^{inner.strip()}]"
    if node.name == "br":
        return "  \n"
    return inner


def _md_escape(text: str) -> str:
    """Escape only what would otherwise start a block construct."""
    return re.sub(r"^(\s*)([#>*+-]|\d+\.)(\s)", r"\1\\\2\3", text)


def _md_table(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [
            " ".join(_md_inline(c) for c in cell.children).strip().replace("|", "\\|")
            for cell in tr.find_all(["th", "td"])
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head, *body = rows
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join(["---"] * width) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(out)


def _md_block(node: Tag, depth: int = 0) -> list[str]:
    name = node.name

    if name in ("h2", "h3", "h4"):
        level = "#" * (int(name[1]))
        return [f"{level} {_md_inline(node).strip()}"]

    if name == "p":
        text = _md_inline(node).strip()
        return [_md_escape(text)] if text else []

    if name in ("ul", "ol"):
        out = []
        for i, li in enumerate(node.find_all("li", recursive=False), start=1):
            marker = "-" if name == "ul" else f"{i}."
            # Nested lists first, so they can be indented under their item.
            nested = []
            for child in li.find_all(["ul", "ol"], recursive=False):
                nested += _md_block(child, depth + 1)
                child.extract()
            text = _md_inline(li).strip()
            pad = "  " * depth
            out.append(f"{pad}{marker} {text}" if text else "")
            out += [textwrap.indent(n, "  " * (depth + 1)) for n in nested]
        return ["\n".join(x for x in out if x)]

    if name == "blockquote":
        inner = []
        for child in node.children:
            if isinstance(child, Tag):
                inner += _md_block(child, depth)
        body = "\n\n".join(inner) or _md_inline(node).strip()
        return [textwrap.indent(body, "> ", lambda _: True)]

    if name == "pre":
        return ["```\n" + node.get_text().strip("\n") + "\n```"]

    if name == "figure":
        cap = node.find("figcaption")
        caption = _md_inline(cap).strip() if cap else ""

        # _wrap_tables puts every table inside a <figure> so the page-break
        # rules have something atomic to hold. Look for that before assuming a
        # figure means an image, or tables disappear from the output entirely.
        table = node.find("table")
        if table is not None:
            rendered = _md_table(table)
            if not rendered:
                return []
            return [rendered + (f"\n\n*{caption}*" if caption else "")]

        img = node.find("img")
        if img is None:
            return [f"*{caption}*"] if caption else []
        # Markdown is a text format; point at the file rather than inlining a
        # megabyte of base64 into something meant to be read as source. The
        # src has already been rewritten to its sidecar-relative path by
        # write_markdown, which is also what copied the file there.
        target = img.get("src", "")
        alt = (img.get("alt") or caption or "").replace("]", "\\]")
        line = f"![{alt}]({target})"
        return [line + (f"\n\n*{caption}*" if caption else "")]

    if name == "table":
        rendered = _md_table(node)
        return [rendered] if rendered else []

    if name == "hr":
        return ["---"]

    if name in ("div", "section", "article", "main", "nav", "header"):
        out = []
        for child in node.children:
            if isinstance(child, Tag):
                out += _md_block(child, depth)
        return out

    text = _md_inline(node).strip()
    return [text] if text else []


def write_markdown(art: Article, output_path: str, *, images_dir: str | None = None) -> None:
    """
    Markdown with YAML front matter, for a notes folder or a git-tracked archive.

    Images are referenced by filename rather than embedded: Markdown is meant to
    be legible as source, and a base64 blob in the middle of it is not.
    `images_dir`, when given, receives copies of the image files.
    """
    soup = BeautifulSoup(art.body_html, "lxml")
    body = soup.body or soup

    # Images live in a sidecar folder next to the .md file, named after it, and
    # are renamed to something readable — the extractor's cache names them by
    # content hash, which is meaningless in a document you intend to read.
    if images_dir is None:
        stem = os.path.splitext(os.path.basename(output_path))[0]
        images_dir = os.path.join(os.path.dirname(os.path.abspath(output_path)),
                                  f"{stem}_files")
    folder = os.path.basename(images_dir)

    kept = 0
    for img in body.find_all("img"):
        path = _local_path(img.get("src", ""))
        if path is None:
            img.decompose()
            continue
        kept += 1
        name = f"figure-{kept}{os.path.splitext(path)[1] or '.png'}"
        os.makedirs(images_dir, exist_ok=True)
        with open(path, "rb") as src_fh:
            data = src_fh.read()
        with open(os.path.join(images_dir, name), "wb") as dst_fh:
            dst_fh.write(data)
        img["src"] = f"{folder}/{name}"

    blocks: list[str] = []
    for child in body.children:
        if isinstance(child, Tag):
            blocks += _md_block(child)

    def _yaml(value: str) -> str:
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

    front = ["---", f"title: {_yaml(art.title)}"]
    if art.byline:
        front.append(f"author: {_yaml(art.byline)}")
    if art.site:
        front.append(f"site: {_yaml(art.site)}")
    if art.published:
        front.append(f"published: {_yaml(art.published)}")
    if art.source_url:
        front.append(f"source: {_yaml(art.source_url)}")
    if art.lang:
        front.append(f"lang: {_yaml(art.lang)}")
    front += [f"retrieved: {date.today():%Y-%m-%d}",
              f"words: {art.word_count}", "---", ""]

    parts = front + [f"# {art.title}", ""]
    parts.append("\n\n".join(b for b in blocks if b.strip()))

    if art.endnotes:
        parts += ["", "## Links in this article", ""]
        parts += [f"{i}. [{text.strip()}]({url})"
                  for i, (text, url) in enumerate(art.endnotes, start=1)]

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts).rstrip() + "\n")


# --------------------------------------------------------------------------
# EPUB 3
# --------------------------------------------------------------------------

EPUB_CSS = """
html { font-size: 100%; }
body { margin: 0 5%; line-height: 1.6; }
h1 { font-size: 1.6em; line-height: 1.25; margin: 0 0 0.4em; }
h2 { font-size: 1.25em; margin: 1.8em 0 0.5em; }
h3 { font-size: 1.1em; margin: 1.4em 0 0.4em; }
p { margin: 0; text-align: justify; }
p + p { text-indent: 1.4em; }
h2 + p, h3 + p, figure + p, blockquote + p, ul + p, ol + p, pre + p,
p.w2p-lead { text-indent: 0; margin-top: 0.8em; }
.w2p-meta { font-size: 0.8em; color: #666; margin-bottom: 1.5em; }
.w2p-standfirst { font-style: italic; color: #444; margin: 1em 0 2em; }
blockquote { margin: 1em 0 1em 1em; padding-left: 1em;
             border-left: 3px solid #ccc; color: #444; }
blockquote p { text-indent: 0; }
figure { margin: 1.5em 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; height: auto; }
figcaption { font-size: 0.82em; color: #666; margin-top: 0.5em; }
table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
th, td { border: 1px solid #ccc; padding: 0.35em 0.5em; text-align: left; }
th { background: #f4f4f4; }
pre { background: #f5f5f5; padding: 0.7em; overflow-x: auto;
      white-space: pre-wrap; font-size: 0.85em; }
.w2p-colophon { font-size: 0.75em; color: #888; margin-top: 3em;
                border-top: 1px solid #ddd; padding-top: 0.8em; }
"""

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

# Void elements must be self-closed in XHTML, and unescaped ampersands are a
# hard parse error in an EPUB reader rather than something it recovers from.
VOID = ("img", "br", "hr", "meta", "link")


def _xhtml_fragment(soup_body: Tag) -> str:
    out = soup_body.decode_contents()
    for tag in VOID:
        out = re.sub(rf"<{tag}([^>]*?)(?<!/)>", rf"<{tag}\1/>", out)
    return out


def write_epub(art: Article, output_path: str, *, toc_entries=None) -> None:
    """
    A reflowable EPUB 3, for reading on a device that reflows.

    An A4 PDF is the wrong object on a phone or a Kobo: the page is fixed and
    the reader has to zoom. The same cleaned Article makes a good EPUB with
    almost no extra work, which is the argument for keeping extraction and
    rendering apart.
    """
    soup = BeautifulSoup(art.body_html, "lxml")
    body = soup.body or soup

    images: list[tuple[str, str, str]] = []   # (id, filename, mimetype)
    for index, img in enumerate(body.find_all("img"), start=1):
        path = _local_path(img.get("src", ""))
        if path is None:
            img.decompose()
            continue
        name = f"img{index}{os.path.splitext(path)[1] or '.jpg'}"
        mime, _ = mimetypes.guess_type(name)
        images.append((f"img{index}", path, mime or "image/jpeg"))
        img["src"] = f"images/{name}"
        if img.has_attr("style"):
            del img["style"]
        if not img.get("alt"):
            img["alt"] = ""

    esc = html_lib.escape
    meta_bits = " · ".join(x for x in (art.byline, art.site, art.published) if x)
    stand = (f'<p class="w2p-standfirst">{esc(art.excerpt)}</p>'
             if art.excerpt and len(art.excerpt) > 60 else "")
    origin = art.source_url or art.site or "a local file"

    endnotes = ""
    if art.endnotes:
        items = "".join(f"<li>{esc(t[:110])} — {esc(u)}</li>"
                        for t, u in art.endnotes)
        endnotes = ("<section><h2>Links in this article</h2>"
                    f"<ol>{items}</ol></section>")

    chapter = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{esc(art.lang or 'en')}"
      lang="{esc(art.lang or 'en')}">
<head>
  <meta charset="utf-8"/>
  <title>{esc(art.title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <h1>{esc(art.title)}</h1>
  <p class="w2p-meta">{esc(meta_bits)}</p>
  {stand}
  {_xhtml_fragment(body)}
  {endnotes}
  <p class="w2p-colophon">From {esc(origin)} · {art.word_count:,} words ·
     prepared {date.today():%d %B %Y}</p>
</body>
</html>
"""

    nav_items = "".join(
        f'<li><a href="chapter.xhtml#{anchor}">{esc(text)}</a></li>'
        for level, anchor, text in (toc_entries or art.sections) if level == 2
    )
    nav = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{esc(art.lang or 'en')}">
<head><meta charset="utf-8"/><title>Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Contents</h1>
    <ol><li><a href="chapter.xhtml">{esc(art.title)}</a>
      {f"<ol>{nav_items}</ol>" if nav_items else ""}
    </li></ol>
  </nav>
</body>
</html>
"""

    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    for img_id, path, mime in images:
        name = f"img{img_id[3:]}{os.path.splitext(path)[1] or '.jpg'}"
        manifest.append(
            f'<item id="{img_id}" href="images/{name}" media-type="{mime}"/>')

    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{esc(art.title)}</dc:title>
    <dc:language>{esc(art.lang or 'en')}</dc:language>
    {f'<dc:creator>{esc(art.byline)}</dc:creator>' if art.byline else ''}
    {f'<dc:publisher>{esc(art.site)}</dc:publisher>' if art.site else ''}
    {f'<dc:description>{esc(art.excerpt)}</dc:description>' if art.excerpt else ''}
    {f'<dc:source>{esc(art.source_url)}</dc:source>' if art.source_url else ''}
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    {chr(10).join('    ' + m for m in manifest).strip()}
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
"""

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        # The mimetype entry must come first and be stored uncompressed; readers
        # sniff it at a fixed byte offset.
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/chapter.xhtml", chapter)
        z.writestr("OEBPS/style.css", EPUB_CSS)
        for img_id, path, _mime in images:
            name = f"img{img_id[3:]}{os.path.splitext(path)[1] or '.jpg'}"
            z.write(path, f"OEBPS/images/{name}")
