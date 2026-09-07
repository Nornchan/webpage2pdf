#!/usr/bin/env python3
"""
Real-world checks — extraction against actual, unmodified production markup.

test_robustness.py covers malformed and synthetic edge cases; test_pipeline.py
covers formats and settings built on top of extraction. Neither ever ran the
extractor against a real templating system's actual output, and real
templating systems produce patterns no hand-written fixture happened to
reproduce: a document root whose own class list coincidentally matches a
furniture-stripping regex, a heading with no sibling of its own because the
skin wraps it alone in a div, a locally saved page's scheme-relative image
URLs, an HTML comment carrying internal cache metadata. All four caused real,
silent data loss or content corruption, and all four are now regression-
guarded here. See tests/fixtures/real-world/MANIFEST.md for the full story
and the source/license of each snapshot.

Deliberately offline and deterministic: every check runs with
download_images=False, and the one assertion that depends on the earlier
scheme-relative image bug is a direct, network-free unit test of the helper
that fixes it, rather than a live fetch. A test suite that needs the network
is a test suite that fails on someone else's unrelated change.

    python3 tests/test_realworld.py
"""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "real-world")

try:
    from webpage2pdf import converter, extractor
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
    from webpage2pdf import converter, extractor  # noqa: E402

GREEN, RED, DIM, OFF = ("\033[32m", "\033[31m", "\033[2m", "\033[0m") \
    if sys.stdout.isatty() else ("", "", "", "")

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))


def extract_fixture(filename, url, **kwargs):
    path = os.path.join(FIXTURES, filename)
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    return extractor.extract(raw, url, tempfile.mkdtemp(),
                             download_images=False, **kwargs)


def main() -> int:
    # ---- the scheme-relative / file:// regression, tested directly ------
    # Bug 3: resolving "//host/path" against a file:// base (what every
    # locally saved page uses) used to produce "file://host/path" — a
    # nonsensical URL that silently dropped every image on the page.
    saved_page_base = f"file://{FIXTURES}/wikipedia-intermodal-container.html"
    resolved = extractor._resolve_url(
        saved_page_base,
        "//upload.wikimedia.org/wikipedia/commons/thumb/d/df/x.jpg")
    check("scheme-relative URL resolves to https from a saved page",
          resolved == "https://upload.wikimedia.org/wikipedia/commons/thumb/d/df/x.jpg",
          resolved)
    check("scheme-relative URL still resolves correctly from a real http(s) page",
          extractor._resolve_url("https://example.com/page.html",
                                 "//cdn.example.com/x.jpg")
          == "https://cdn.example.com/x.jpg")
    check("an ordinary relative path is unaffected",
          extractor._resolve_url("https://example.com/dir/page.html", "img/x.jpg")
          == "https://example.com/dir/img/x.jpg")

    # ---- Wikipedia: MediaWiki Vector 2022 -------------------------------
    wiki = extract_fixture("wikipedia-intermodal-container.html",
                           "https://en.wikipedia.org/wiki/Intermodal_container")

    # Bug 1: <html class="...main-menu-disabled...vector-toc-available...">
    # matched the furniture regex on "menu"/"toc" substrings and, with no
    # floor on the sweep, took the whole document down with it.
    check("wikipedia: title recovered (not destroyed by the html-root bug)",
          wiki.title == "Intermodal container", wiki.title)
    check("wikipedia: substantial article text recovered",
          wiki.word_count > 5000, wiki.word_count)

    # Bug 2: each heading alone in its own <div> had no *sibling* once the
    # edit-section link beside it was stripped, so find_next_sibling()
    # misjudged every section heading as an empty label and deleted it.
    check("wikipedia: section headings survived (not all deleted as 'empty')",
          len(wiki.sections) > 10, len(wiki.sections))
    top_level = [text for level, _, text in wiki.sections if level == 2]
    check("wikipedia: a real top-level section title is present",
          "History" in top_level, top_level[:5])

    # Bug 4: an HTML comment carrying a Parsoid cache key was promoted into a
    # visible <p> and counted in the word total, because bs4.Comment
    # subclasses NavigableString.
    check("wikipedia: no internal cache-key metadata leaked into the article",
          "cache key" not in wiki.body_html and "postproc" not in wiki.body_html)
    check("wikipedia: no Parsoid version string leaked into the article",
          "Parsoid" not in wiki.body_html)

    # General furniture removal, still worth checking on a real page.
    lowered = wiki.body_html.lower()
    for junk in ("jump to navigation", "edit section", "from wikipedia,",
                "download qr code", "printable version"):
        check(f"wikipedia: no leaked chrome ({junk!r})", junk not in lowered)

    # ---- Python docs: a clean-case control ------------------------------
    # No known bug lives here; this is the fixture that tells you a change
    # broke something on *ordinary* real markup, not only the adversarial
    # cases above.
    pydocs = extract_fixture("python-docs-tutorial.html",
                             "https://docs.python.org/3/tutorial/introduction.html")
    check("python docs: title recovered",
          "Informal Introduction" in pydocs.title, pydocs.title)
    check("python docs: substantial text recovered", pydocs.word_count > 2000,
          pydocs.word_count)
    check("python docs: a code sample survived", ">>> " in pydocs.body_html
          or "<pre" in pydocs.body_html)
    check("python docs: sections recovered", len(pydocs.sections) > 0,
          len(pydocs.sections))

    # ---- paulgraham.com: adversarial control ----------------------------
    # 1990s-era markup: nested layout tables, no semantic tags, no
    # <article>/<main> to anchor scoring on. Confirms the scorer can still
    # find the article with zero structural help, not just on modern markup.
    pg = extract_fixture("paulgraham-life-is-short.html",
                         "http://www.paulgraham.com/vb.html")
    check("paulgraham: title recovered from table-layout markup",
          pg.title == "Life is Short", pg.title)
    check("paulgraham: substantial text recovered despite no semantic tags",
          pg.word_count > 1000, pg.word_count)

    # ---- every fixture converts to an actual, valid PDF ------------------
    # Extraction-level checks above are the precise regression guards; this
    # is the coarse "does the whole pipeline still survive real markup"
    # check — nested tables, huge documents, and code blocks have each
    # broken renderers in this project's history in ways that only show up
    # once WeasyPrint is actually involved.
    for filename in ("wikipedia-intermodal-container.html",
                     "python-docs-tutorial.html",
                     "paulgraham-life-is-short.html"):
        out = tempfile.mktemp(suffix=".pdf")
        path = os.path.join(FIXTURES, filename)
        try:
            result = converter.convert(path, out, images=False)
            with open(out, "rb") as fh:
                head = fh.read(4)
            check(f"{filename}: renders to a valid PDF",
                  head == b"%PDF" and result.pages > 0,
                  f"pages={result.pages}")
        except Exception as exc:  # pragma: no cover - failure is the report
            check(f"{filename}: renders to a valid PDF", False,
                  f"{type(exc).__name__}: {exc}")
        finally:
            if os.path.exists(out):
                os.remove(out)

    print("\nReal-world checks")
    print("-" * 60)
    failed = 0
    for name, ok, detail in results:
        if ok:
            print(f"  {GREEN}PASS{OFF}  {name}")
        else:
            failed += 1
            print(f"  {RED}FAIL{OFF}  {name}  {DIM}{detail}{OFF}")
    print(f"\n  {len(results) - failed} passed, {failed} failed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
