#!/usr/bin/env python3
"""
Robustness checks — the malformed and awkward inputs that break converters.

    python3 tests/test_robustness.py

Each case must either produce a valid PDF or fail with a clear message. What it
must never do is crash, hang, or emit a corrupt file.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Prefer an installed webpage2pdf; fall back to the source tree so the suite
# runs in a fresh checkout before `pip install`.
try:
    from webpage2pdf import converter, extractor
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
    from webpage2pdf import converter, extractor  # noqa: E402

CASES: list[tuple[str, str]] = [
    ("unclosed tags", """
        <html><body><article>
        <h1>Broken markup
        <p>A paragraph that is never closed, containing <b>bold text
        <p>And another one after it, with an <em>unclosed emphasis
        <div><span>Nested chaos
        """ + "<p>Body sentence number %d with enough words to register as prose.</p>" * 1 % 1
        + "".join(f"<p>Filler paragraph {i} carrying sufficient words to be counted as real prose content here.</p>" for i in range(8))
        + "</body></html>"),

    ("no article container", """
        <html><body>
        <h1>Just a bare page</h1>
        """ + "".join(f"<p>This page has no semantic wrapper at all, only paragraph {i} "
                      f"sitting directly in the body with a reasonable amount of text.</p>"
                      for i in range(10)) + "</body></html>"),

    ("deeply nested divs", """<html><body><main>""" + "<div>" * 40 +
     "<h1>Buried</h1>" +
     "".join(f"<p>Paragraph {i} buried forty divs deep, which is not unusual for a "
             f"modern site built by a component framework.</p>" for i in range(9)) +
     "</div>" * 40 + "</main></body></html>"),

    ("no headings at all", "<html><body><article>" +
     "".join(f"<p>Unbroken prose paragraph {i} with no heading structure whatsoever, "
             f"which the heading remapper must survive without complaint.</p>"
             for i in range(12)) + "</article></body></html>"),

    ("headings starting at h4", "<html><body><article><h1>Title</h1>" +
     "".join(f"<h4>Section {i}</h4><p>Prose under a section that the source document "
             f"labelled h4 for no good reason, paragraph {i} of the body text.</p>"
             for i in range(5)) + "</article></body></html>"),

    ("broken image sources", "<html><body><article><h1>Bad images</h1>" +
     '<img src="http://127.0.0.1:1/nope.jpg" alt="unreachable host">'
     '<img src="" alt="empty">'
     '<img alt="no src at all">'
     '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" alt="pixel">'
     '<img src="/does/not/exist.png" alt="missing local">' +
     "".join(f"<p>Text paragraph {i} that must still survive the image failures "
             f"happening around it in this document.</p>" for i in range(8)) +
     "</article></body></html>"),

    ("table without thead", "<html><body><article><h1>Tables</h1>" +
     "<table>" + "".join(f"<tr><td>Row {i} cell A</td><td>Row {i} cell B</td></tr>"
                         for i in range(40)) + "</table>" +
     "".join(f"<p>Surrounding paragraph {i} with adequate prose for scoring.</p>"
             for i in range(8)) + "</article></body></html>"),

    ("entities and unicode", "<html><body><article><h1>Entities &amp; scripts</h1>" +
     "<p>Ampersands &amp; angle brackets &lt;like this&gt;, non-breaking&nbsp;spaces, "
     "em&mdash;dashes, curly “quotes”, accents (naïve, café), "
     "Greek (αβγ), Chinese (中文段落), "
     "Japanese (日本語), Arabic (العربية), "
     "and emoji ✈ ☀.</p>" +
     "".join(f"<p>Follow-up paragraph {i} keeping the word count respectable for "
             f"the content scorer to accept this document.</p>" for i in range(8)) +
     "</article></body></html>"),

    ("empty document", "<html><body></body></html>"),

    ("text with no html", "Just a bare string of text, no tags at all."),

    ("script-only page", "<html><body><script>document.write('hi')</script>"
                         "<noscript>Enable JavaScript</noscript></body></html>"),

    ("nested tables", "<html><body><article><h1>Nested</h1>"
     "<table><tr><td><table><tr><td>inner cell</td></tr></table></td></tr></table>" +
     "".join(f"<p>Paragraph {i} beside a nested table layout of the sort older "
             f"sites still use for page structure.</p>" for i in range(8)) +
     "</article></body></html>"),

    ("very long single paragraph", "<html><body><article><h1>Wall of text</h1><p>" +
     ("This sentence repeats many times to build one enormous paragraph. " * 400) +
     "</p></article></body></html>"),

    ("pre and code blocks", "<html><body><article><h1>Code</h1>"
     "<pre><code>def f(x):\n    return [very_long_identifier_name_here(y) for y in x "
     "if y is not None and y > 0]\n</code></pre>" +
     "".join(f"<p>Explanatory paragraph {i} around the code sample above it.</p>"
             for i in range(8)) + "</article></body></html>"),
]


def run() -> int:
    tmp = tempfile.mkdtemp(prefix="w2p-tests-")
    passed = failed = 0

    for name, html in CASES:
        src = os.path.join(tmp, name.replace(" ", "-") + ".html")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(html)
        out = os.path.join(tmp, name.replace(" ", "-") + ".pdf")

        try:
            result = converter.convert(src, out, link_mode="endnotes")
            ok = os.path.isfile(out) and os.path.getsize(out) > 800
            with open(out, "rb") as fh:
                ok = ok and fh.read(5) == b"%PDF-"
            if ok:
                passed += 1
                note = f"{result.pages}p, {result.word_count}w"
                if result.warnings:
                    note += f", warned: {result.warnings[0][:40]}…"
                print(f"  PASS  {name:32} {note}")
            else:
                failed += 1
                print(f"  FAIL  {name:32} produced an invalid PDF")
        except Exception as exc:
            # A clear failure on genuinely empty input is acceptable behaviour.
            if "empty" in name or "script-only" in name:
                passed += 1
                print(f"  PASS  {name:32} declined cleanly: {type(exc).__name__}")
            else:
                failed += 1
                print(f"  FAIL  {name:32} {type(exc).__name__}: {exc}")

    # Encoding round-trip: a GB18030 file with no BOM must not mojibake.
    try:
        path = os.path.join(tmp, "gb18030.html")
        body = ("<html><head><meta charset='gb18030'></head><body><article>"
                "<h1>中文标题</h1>"
                + "".join(f"<p>这是第{i}段中文正文"
                          f"，用来测试编码处理"
                          f"是否正确。</p>" for i in range(10))
                + "</article></body></html>")
        with open(path, "wb") as fh:
            fh.write(body.encode("gb18030"))
        html_text, _ = extractor.read_local(path)
        if "中文标题" in html_text:
            passed += 1
            print(f"  PASS  {'gb18030 encoding':32} decoded correctly")
        else:
            failed += 1
            print(f"  FAIL  {'gb18030 encoding':32} mojibake")
    except Exception as exc:
        failed += 1
        print(f"  FAIL  {'gb18030 encoding':32} {exc}")

    # Image de-dup and print-hidden furniture: a page that ships its hero
    # image twice (the responsive-markup pattern — one <img> per breakpoint)
    # and puts a "related articles" rail in a print:hidden block. The hero
    # must print once; the rail must not print at all.
    try:
        from PIL import Image  # noqa: PLC0415

        hero = os.path.join(tmp, "hero.png")
        Image.new("RGB", (900, 560), (120, 90, 60)).save(hero)
        rel = os.path.join(tmp, "related.png")
        Image.new("RGB", (600, 400), (60, 90, 120)).save(rel)
        hero_url = "file://" + hero
        rel_url = "file://" + rel

        html = (
            "<html lang='en'><head><title>Dupe hero</title></head><body><main>"
            "<article><h1>The article</h1>"
            f"<div class='hero md:hidden print:hidden'><img src='{hero_url}' "
            "alt='the lead photograph, shown on small screens'></div>"
            f"<div class='hero hidden md:block print:hidden'><img src='{hero_url}' "
            "alt='the lead photograph, shown on large screens'></div>"
            + "".join(f"<p>Body paragraph {i} with enough real words in it to "
                      f"register as genuine article prose rather than a caption.</p>"
                      for i in range(10))
            + "</article>"
            "<div class='recirc print:hidden'><h2>More from us</h2>"
            f"<a href='https://example.com/x'><img src='{rel_url}' "
            "alt='thumbnail for a recommended article'>An unrelated recommended piece</a>"
            "<p>Recommended teaser text that must never reach the PDF.</p></div>"
            "</main></body></html>")

        path = os.path.join(tmp, "dupe-hero.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)

        art = extractor.extract(html, "file://" + path, tempfile.mkdtemp())
        ok = (art.images == 1
              and art.body_html.count("<img") == 1
              and "recommended" not in art.body_html.lower()
              and "More from us" not in art.body_html)
        if ok:
            passed += 1
            print(f"  PASS  {'dedup hero + print:hidden rail':32} 1 image, no recirc")
        else:
            failed += 1
            print(f"  FAIL  {'dedup hero + print:hidden rail':32} "
                  f"images={art.images}, imgtags={art.body_html.count('<img')}")
    except ImportError:
        print(f"  SKIP  {'dedup hero + print:hidden rail':32} Pillow not installed")
    except Exception as exc:
        failed += 1
        print(f"  FAIL  {'dedup hero + print:hidden rail':32} {type(exc).__name__}: {exc}")

    # Recirculation rails on a page with no usable class names. NYT ships
    # Emotion hashes ("css-1qiat4j"), so every token-matching sweep is blind to
    # it: a real article came out 23 pages, 17 of them "More in Europe" and
    # "Editors' Picks" rails promoted into the table of contents as chapters.
    # The rails must go; the article, and a prose section whose heading happens
    # to match, must both survive untouched.
    rail_cases = [
        ("hashed-class recirc rail", True, "More in Europe",
         "<section class='css-1qiat4j'><h2>Related Content</h2>"
         "<section class='css-8atqhb'><h3>More in Europe</h3><ul>"
         + "".join(f"<li><a href='https://www.nytimes.com/x{i}'>"
                   f"<img src='https://static01.nyt.com/img{i}.jpg' alt=''>"
                   f"<h3>A European headline of ordinary length, number {i}</h3></a>"
                   f"<p class='css-1c0pn3'>Agence France-Presse — Getty Images</p></li>"
                   for i in range(6))
         + "</ul></section></section>"),
        ("flat rail with no wrapper", True, "You might also like",
         "<h2>You might also like</h2>"
         + "".join(f"<div><a href='/x{i}'>Another headline about European politics, "
                   f"number {i}</a><p>Getty Images</p></div>" for i in range(6))),
        ("prose section that merely matches", False, "Related concepts",
         "<h2>Related concepts</h2>"
         "<p>Manipulation differs from persuasion in that it bypasses a person's "
         "rational agency, and that distinction matters for how we judge an appeal.</p>"
         "<p>Coercion, by contrast, removes the option outright rather than merely "
         "clouding the reasoning that leads someone toward a particular choice.</p>"),
    ]
    body = "".join(f"<p>Body paragraph {i} carrying enough genuine sentences to read "
                   f"as real article prose rather than a caption.</p>" for i in range(12))
    for label, should_vanish, probe, block in rail_cases:
        try:
            html = ("<html lang='en'><head><title>Rails</title></head><body><main>"
                    f"<article><h1>The article</h1>{body}{block}</article>"
                    "</main></body></html>")
            path = os.path.join(tmp, f"rail-{abs(hash(label))}.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
            art = extractor.extract(html, "file://" + path, tempfile.mkdtemp(),
                                    download_images=False)
            gone = probe.lower() not in art.body_html.lower()
            kept_article = "Body paragraph 11" in art.body_html
            if gone == should_vanish and kept_article:
                passed += 1
                print(f"  PASS  {label:32} "
                      f"{'rail removed' if should_vanish else 'prose kept'}, article intact")
            else:
                failed += 1
                print(f"  FAIL  {label:32} gone={gone} expected={should_vanish} "
                      f"article_intact={kept_article}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {label:32} {type(exc).__name__}: {exc}")

    print(f"\n  {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    print("\nRobustness checks\n" + "-" * 60)
    sys.exit(run())
