#!/usr/bin/env python3
"""
Pipeline checks — formats, profiles, presets, settings resolution, cache.

test_robustness.py covers the extractor against malformed input. This covers
everything built on top of it: that each format produces a file of the right
shape, that a profile means what it says, that flags beat profiles and profiles
beat defaults, and that the cache is actually consulted.

    python3 tests/test_pipeline.py
"""

import os
import re
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    from webpage2pdf import cache, cli, converter, presets, profiles, writers
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
    from webpage2pdf import cache, cli, converter, presets, profiles, writers  # noqa: E402

GREEN, RED, DIM, OFF = ("\033[32m", "\033[31m", "\033[2m", "\033[0m") \
    if sys.stdout.isatty() else ("", "", "", "")

ARTICLE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>A Test Article</title><meta name="author" content="A Writer">
<meta property="og:site_name" content="A Journal"></head><body>
<nav><a href="/">Home</a></nav>
<article><h1>A Test Article</h1>
""" + "".join(
    f"<h2>Section {i}</h2>" + "<p>Prose with commas, clauses, and enough "
    "length that the scorer counts it as a real paragraph rather than "
    "furniture or a list of links.</p>" * 6
    for i in range(1, 6)
) + """<table><thead><tr><th>Year</th><th>Value</th></tr></thead>
<tbody><tr><td>1956</td><td>5.86</td></tr></tbody></table>
</article><footer>Copyright</footer></body></html>"""

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="w2p-pipeline-")

    # Isolate from the developer's own config: a ~/.config/webpage2pdf holding
    # a different default profile, or a user profile shadowing a built-in name,
    # would otherwise make these assertions fail on their machine and pass on
    # everyone else's.
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")

    src = os.path.join(tmp, "article.html")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(ARTICLE)

    # ---- every format produces a file of the right shape -----------------
    shapes = {
        "pdf": lambda b: b[:4] == b"%PDF",
        "html": lambda b: b"<!DOCTYPE html>" in b[:200],
        "epub": lambda b: b[:2] == b"PK",
        "md": lambda b: b.startswith(b"---\ntitle:"),
    }
    for fmt, valid in shapes.items():
        out = os.path.join(tmp, f"out.{fmt}")
        converter.convert(src, out, fmt=fmt)
        with open(out, "rb") as fh:
            head = fh.read(400)
        check(f"format {fmt} produces a valid file", valid(head))

    # ---- the EPUB is structurally sound ----------------------------------
    with zipfile.ZipFile(os.path.join(tmp, "out.epub")) as z:
        names = z.namelist()
        info = z.getinfo("mimetype")
        opf = z.read("OEBPS/content.opf").decode()
    check("epub mimetype is first and stored",
          names[0] == "mimetype" and info.compress_type == zipfile.ZIP_STORED)
    check("epub declares dcterms:modified (spec requires it)",
          "dcterms:modified" in opf)
    check("epub carries the author through", "A Writer" in opf)

    # ---- markdown keeps tables -------------------------------------------
    # Regression: tables are wrapped in <figure>, and the figure branch once
    # assumed a figure meant an image, so they vanished silently.
    with open(os.path.join(tmp, "out.md"), encoding="utf-8") as fh:
        md = fh.read()
    check("markdown keeps tables", "| Year | Value |" in md)
    check("markdown has front matter", md.startswith("---\ntitle:"))

    # ---- standalone HTML has no external references ----------------------
    with open(os.path.join(tmp, "out.html"), encoding="utf-8") as fh:
        html = fh.read()
    external = [u for u in re.findall(r'(?:src|href)="([^"]+)"', html)
                if not u.startswith(("data:", "#"))]
    check("standalone html has no external references", not external,
          ", ".join(external[:3]))
    check("standalone html embeds fonts", html.count("@font-face") >= 1)

    # ---- presets change the page, and a4 is unchanged --------------------
    a4 = presets.get("a4")
    check("a4 preset still measures 160mm", abs(a4.text_width_mm - 160.0) < 0.01)
    check("a4 image box still 195mm", abs(a4.text_height_mm - 195.0) < 0.01)
    for name in presets.names():
        page = presets.get(name)
        check(f"preset {name} has a sane text block",
              0 < page.text_width_mm <= page.page_width_mm
              and 0 < page.text_height_mm < page.page_height_mm)

    # ---- profiles and precedence -----------------------------------------
    def settings(argv):
        return cli.resolve_settings(cli.build_parser().parse_args(argv))

    check("default profile is essay/pdf/a4",
          settings(["x.html"])["fmt"] == "pdf"
          and settings(["x.html"])["preset"] == "a4")
    check("profile selects a format", settings(["--profile", "notes", "x.html"])["fmt"] == "md")
    check("output filename beats the profile",
          settings(["--profile", "notes", "-o", "a.pdf", "x.html"])["fmt"] == "pdf")
    check("an explicit flag beats the filename",
          settings(["--profile", "notes", "-o", "a.pdf", "-f", "epub", "x.html"])["fmt"] == "epub")
    check("a flag overrides one part of a profile",
          settings(["--profile", "booklet", "--preset", "a4", "x.html"])["preset"] == "a4"
          and settings(["--profile", "booklet", "--preset", "a4", "x.html"])["links"] == "footnotes")

    for bad in (["--profile", "nope", "x.html"], ["--preset", "nope", "x.html"]):
        try:
            settings(bad)
            check(f"rejects {bad[0]} {bad[1]}", False, "no error raised")
        except ValueError:
            check(f"rejects {bad[0]} {bad[1]}", True)

    # ---- cache -----------------------------------------------------------
    store = cache.Cache(directory=os.path.join(tmp, "cache"))
    check("cache misses when empty", store.get_page("http://x/") is None)
    store.put_page("http://x/", "<html>y</html>", "http://x/final")
    check("cache round-trips a page",
          store.get_page("http://x/") == ("<html>y</html>", "http://x/final"))
    disabled = cache.Cache(directory=os.path.join(tmp, "cache"), enabled=False)
    check("a disabled cache never hits", disabled.get_page("http://x/") is None)
    refreshing = cache.Cache(directory=os.path.join(tmp, "cache"), refresh=True)
    check("--refresh treats held entries as stale",
          refreshing.get_page("http://x/") is None)

    # ---- filenames and atomic claiming -----------------------------------
    check("filename takes the format's extension",
          converter.suggest_filename("A Title", fmt="epub") == "A-Title.epub")
    first = converter.claim_output_path(os.path.join(tmp, "claim.pdf"))
    second = converter.claim_output_path(os.path.join(tmp, "claim.pdf"))
    check("claiming a taken name yields a fresh one",
          os.path.basename(first) == "claim.pdf"
          and os.path.basename(second) == "claim-2.pdf")

    shutil.rmtree(tmp, ignore_errors=True)

    print("\nPipeline checks")
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
