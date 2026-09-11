# webpage2pdf

[![CI](https://github.com/Nornchan/webpage2pdf/actions/workflows/ci.yml/badge.svg)](https://github.com/Nornchan/webpage2pdf/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Nornchan/webpage2pdf)](https://github.com/Nornchan/webpage2pdf/releases/latest)

Turns web pages into clean A4 PDFs that read like typeset essays instead of screenshots of a website.

Saving a page from your browser keeps the site's screen layout and hands the pagination to a print engine that treats page-break rules as optional. You get sidebars, cookie banners, images sliced across two pages, and headings stranded at the foot of a page. This tool does something different: it works out which part of the page is actually the article, throws the rest away, and re-typesets the content from scratch for paper.

---

## Setup

**With Homebrew:**

```bash
brew install Nornchan/tap/webpage2pdf
```

That puts three commands on your `PATH`: `webpage2pdf`, the shorter alias
`w2p`, and `webpage2pdf-server` (a local drag-and-drop web app). It taps
[`Nornchan/homebrew-tap`](https://github.com/Nornchan/homebrew-tap)
automatically — no separate `brew tap` needed first.

This is the path worth preferring. Homebrew builds the virtualenv from its own
Python with `pango` as a declared dependency, so the library is guaranteed
present and correctly linked — the runtime fix under Troubleshooting still
runs (dyld's default search path never includes `/opt/homebrew/lib`, Homebrew
build or not), it just always finds what it's looking for. A source install
depends on you having separately run `brew install pango` and built the venv
from that same Homebrew Python rather than Anaconda's, which is what the
`libpango-1.0-0` error under Troubleshooting actually is.

**From source, macOS, one time:**

```bash
bash setup.sh
```

That installs Pango (the text-rendering library WeasyPrint needs) via Homebrew, creates a `.venv`, and installs the Python packages.

If you'd rather do it by hand:

```bash
brew install pango
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
```

That puts three commands on your path: `webpage2pdf`, its short alias `w2p`, and `webpage2pdf-server`.

---

## Using it

### The web app

```bash
webpage2pdf-server
```

Opens `http://127.0.0.1:8765`. Paste links or file paths one per line, or drop saved `.html` files onto the page. Pick a profile and it fills in the format, page size, link handling and numbering — visibly, so you can then change any one part of it, the same relationship `--profile` has with the other flags. Finished files land in `~/Documents/webpage2pdf` (override with `-o`) and download with one click.

Nothing is uploaded anywhere — the server binds to `127.0.0.1` only, so it is not reachable from the network, and it shares the fetch cache with the command line, so re-converting a page with different options costs no network at all.

### The command line

```bash
# a single page
webpage2pdf https://example.com/some-essay

# a saved file, named output
webpage2pdf saved-page.html -o reading/week-03.pdf

# a batch into one folder, filenames taken from article titles
w2p url1 url2 saved.html -d reading/

# a week's reading list from a text file
w2p --from-list links.txt -d reading/
```

`w2p` is a shorter alias for `webpage2pdf`; the two are identical. From a source checkout without installing, `python3 -m webpage2pdf` works too.

| Option | Effect |
|---|---|
| `-o FILE` | Exact output path (single source only) |
| `-d DIR` | Output folder; filenames come from article titles |
| `--from-list FILE` | Read sources from a file, one per line, `#` for comments |
| `--links plain\|endnotes\|footnotes\|keep` | Strip link styling, collect links as numbered endnotes, set each URL at the foot of the page it appears on, or keep them live |
| `--no-numbering` | Drop the automatic section and figure numbers |
| `--no-images` | Text only — much smaller files |
| `--no-url` / `--no-standfirst` | Trim the title block |
| `--keep-html FILE` | Also save the cleaned HTML, useful for checking what was removed |
| `--list-profiles` | Show available profiles and exit |
| `-j`, `--jobs N` | Fetch this many pages at once in a batch (default 4) |
| `--cookies FILE` | Send cookies from a file — for pages you can only read signed in |
| `--no-cache` / `--refresh` | Ignore the fetch cache, or re-fetch despite it |
| `--cache-info` / `--clear-cache` | Inspect or empty the cache |
| `--doctor --fix` | Attempt the repairs `--doctor` recommends |
| `-p`, `--profile NAME` | Named bundle of settings — see below |
| `-f`, `--format FMT` | `pdf`, `html`, `epub` or `md` (inferred from `-o` when not given) |
| `--preset NAME` | Page geometry: `a4`, `letter`, `a5`, `book`, `remarkable`, `two-column` |
| `--toc` / `--no-toc` | Force or suppress the contents list (otherwise automatic) |
| `--open` | Open each finished PDF in the default viewer |
| `--list-presets` | Show available page presets and exit |
| `-V`, `--version` | Print the version and exit |
| `--doctor` | Check the installation and report what is wrong |

---

## Formats and profiles

The extractor rebuilds every page into the same small set of semantic tags, so a
PDF is only one of the things that can come out the other end:

```bash
w2p url -o piece.pdf     # A4, typeset for paper
w2p url -o piece.html    # one self-contained file, fonts and images embedded
w2p url -o piece.epub    # reflowable, for a phone or a Kobo
w2p url -o piece.md      # front matter and Markdown, for a notes folder
```

The format comes from the filename, or from `--format`.

A **profile** bundles the settings that go together, because they are not
independent choices — footnotes suit paper and are pointless on screen, section
numbers help a reference document and clutter an essay:

| Profile | Makes |
|---|---|
| `essay` | A4 PDF, quiet links, contents list when the piece is long enough (the default) |
| `reference` | Two columns, numbered sections, footnoted links |
| `booklet` | 6×9in facing pages with mirrored margins, for printing double-sided |
| `device` | Sized to a reMarkable screen |
| `screen` | One self-contained HTML file, live links |
| `ereader` | Reflowable EPUB |
| `notes` | Markdown with YAML front matter |

```bash
w2p --profile booklet --from-list reading.txt -d week-03/
```

Any flag you give overrides the profile. Add your own as TOML in
`~/.config/webpage2pdf/profiles/`:

```toml
# ~/.config/webpage2pdf/profiles/seminar.toml
description = "A5 handout for the reading group"
preset = "a5"
links = "footnotes"
numbered = false
show_url = false
```

It appears in `--list-profiles` immediately. A user profile sharing a built-in
name replaces it.

---

## Speed, pipes and settings you keep

**Fetches are cached**, so converting the same article to a second format, or
trying it against another profile, costs nothing:

```bash
w2p https://example.com/essay -o essay.pdf     # fetches
w2p https://example.com/essay -o essay.epub    # no network at all
```

Pages are held for a day and images for a month, under
`~/Library/Caches/webpage2pdf`. `--refresh` re-fetches, `--no-cache` bypasses it,
`--cache-info` and `--clear-cache` inspect and empty it. Nothing there is
precious; deleting it costs only time.

**Batches fetch in parallel.** `--jobs` (default 4) warms the cache concurrently
before rendering. Rendering stays single-threaded on purpose — WeasyPrint offers
no thread-safety guarantee and drives Pango through cffi with shared fontconfig
state — but the network is the part that actually takes the time. Six pages at
0.6s latency: 5.5s serial, 2.5s parallel.

**It composes.** `-` reads HTML from standard input, `-o -` writes the finished
file to standard output, and progress goes to stderr so it cannot corrupt the
document:

```bash
pbpaste | w2p - -o - > clipping.pdf
curl -s https://example.com/essay | w2p - -o - -f md >> reading-log.md
cat urls.txt | w2p --from-list - -d reading/
```

**Settings you would otherwise retype** go in `~/.config/webpage2pdf/config.toml`:

```toml
profile = "booklet"
dir = "~/Documents/reading"
jobs = 8
open = true
```

Command-line flags still win over the config, and the config only supplies
defaults — per-document choices belong on the command line.

---

## What it actually does

**1. Finds the article.** Every container on the page is scored on how much real prose it holds — paragraph count, text length, comma density — and penalised for link density, which is what separates an article from a list of headlines. Semantic tags (`<article>`, `<main>`) get a bonus. When a wrapper `div` and the article inside it score alike, the tighter one wins.

**2. Removes the furniture.** Two passes, deliberately. A broad sweep first for nav, footers, sidebars, cookie banners and modals; then, once the article is identified, a gentler sweep for share bars, newsletter forms, related-story rails, comments and ad slots. A section is spared if it turns out to be prose-heavy, so a genuine "Related concepts" heading in an explainer survives while a link rail does not.

Anything the page itself marks hidden-when-printing — `print:hidden`, `d-print-none`, `hidden-print` and the rest — is taken at its word and dropped in the first sweep. Component-framework sites use it for exactly the things that don't belong on paper: share bars, and the "more from this site" rail that often sits *inside* `<main>` beside the article where the scorer would otherwise keep it.

Sites that name nothing get a third signal: the heading. A site built on Emotion or styled-components ships hashed class names — `css-1qiat4j` — so there is no token for any of the above to match, and a "Related Content" rail of headline links sails through into the PDF. So a heading that reads like a rail ("More in Europe", "Editors' Picks", "You might also like") marks what follows as a candidate, and it is dropped only if it also *looks* like a rail: most of its text inside links, and not one sentence-length paragraph anywhere in it. A prose section that happens to be called "Related concepts" fails the second test and stays.

Also handled: tables of contents, "edit" permalinks glued to headings, citation superscripts pointing at footnotes that aren't coming with us, and infobox sidebars.

**3. Rebuilds the structure.** Headings are re-levelled so the hierarchy is coherent — if a site starts its sections at `h3`, everything slides up so the top level is `h2`. Div-wrapped prose becomes real paragraphs, `<b>`/`<i>` become `<strong>`/`<em>`, definition lists become bullets, every site class and inline style is stripped, and captions orphaned in sibling divs are pulled into the `<figure>` they describe.

**4. Fixes the images.** Lazy-loaded sources are recovered from `data-src`, `data-original` and friends; `srcset` resolves to the highest-resolution candidate so print stays sharp. Tracking pixels, spacers and icons are dropped on size. An image that appears more than once — the same asset shipped as a separate `<img>` per responsive breakpoint, say — is kept once. Then the important part: **any image tall enough to overflow the text block is scaled down so it fits within a single page.** A 900×2400 diagram becomes 73mm wide rather than being cut in half.

**5. Typesets it.** A4 by default, in bundled Literata — old-style figures in running text, lining tabular figures in tables, justified with hyphenation in the source page's own language, first-line indents. Running heads carry the article title on the left and the current section on the right. Documents with at least four sections and 1500 words get a contents list whose page numbers come from CSS `target-counter`, so they stay correct without a second render.

`--preset` changes the page geometry, and it drives both the stylesheet and the image fitting from one set of numbers:

| Preset | Page | For |
|---|---|---|
| `a4` | 210×297mm | The default |
| `letter` | 215.9×279.4mm | US paper |
| `a5` | 148×210mm | Half of A4, one-handed |
| `book` | 152.4×228.6mm | 6×9in trim, facing pages with mirrored margins, for binding |
| `remarkable` | 157×210mm | reMarkable 2 e-ink, narrow margins to use the glass |
| `two-column` | 210×297mm | Dense reference material |

### Why images stop breaking

Browsers largely ignore `break-inside: avoid` when printing. WeasyPrint enforces it. Combined with the height capping in step 4, a figure is atomic: it moves to the next page whole rather than being sliced. The same rules keep captions attached to their images, table rows intact, headings off the bottom of a page, and short lists together — and `orphans`/`widows` stop single lines being stranded.

---

## Adjusting the look

Everything visual lives in `src/webpage2pdf/styles/essay.css`. Common edits:

| Change | Where |
|---|---|
| Margins | `@page { margin: ... }` |
| Body size / leading | `html { font-size / line-height }` |
| Fonts | `--serif`, `--sans` at the top |
| Ragged-right instead of justified | `p { text-align: left }` |
| No first-line indents | delete the `p + p { text-indent }` rule |

Copy the file to `src/webpage2pdf/styles/handout.css`, edit it, and it appears automatically as `--style handout` and in the web app's dropdown.

**If you change the page margins,** update the geometry constants at the top of `converter.py`, which is what image fitting is measured against.

One trap worth knowing: `TEXT_HEIGHT_MM` is **not** the height of the text block. The block is 250mm (297 − 25 − 22), but the constant is 195mm. The 55mm difference is deliberate headroom. An image is never alone on the page — it carries a caption, and a figure is atomic, so a 250mm-tall image plus a caption makes a figure taller than any page can hold, which forces exactly the split this tool exists to prevent. Change `MARGIN_TOP_MM` / `MARGIN_BOTTOM_MM` to match your new `@page` rule and leave `CAPTION_HEADROOM_MM` alone; `TEXT_HEIGHT_MM` is derived from them.

---

## Troubleshooting

Start here — it checks the interpreter, the native libraries and every package, then tells you the exact fix:

```bash
webpage2pdf --doctor
```

### `OSError: cannot load library 'libpango-1.0-0'`

The most common macOS failure, and it happens *after* `brew install pango` succeeds — so it looks baffling.

WeasyPrint doesn't bundle its text engine; it loads Pango at runtime with `dlopen()`. Homebrew installs Pango in `/opt/homebrew/lib`, which macOS does not search by default. If your venv was built from **Anaconda's** Python (your prompt shows `(base)`), the interpreter looks in `/opt/anaconda3/lib` and never finds it.

`_bootstrap.py` now fixes this automatically: it detects Homebrew's library directory, sets `DYLD_FALLBACK_LIBRARY_PATH`, and re-execs once — because macOS reads that variable only at process start, so setting it from inside a running Python is too late.

If you still hit it, rebuild the venv from Homebrew's Python rather than Anaconda's:

```bash
brew install python pango
cd /path/to/webpage2pdf
rm -rf .venv
/opt/homebrew/bin/python3 -m venv .venv
./.venv/bin/python -m pip install -e .
./.venv/bin/webpage2pdf --doctor
```

**Don't** build the venv from `/usr/bin/python3`. Apple's Python is protected by SIP, which strips `DYLD_FALLBACK_LIBRARY_PATH` at launch — the usual fix silently does nothing.

### Other issues

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: weasyprint` | Using system `python3` instead of the venv. Use `./.venv/bin/webpage2pdf`. |
| `Unknown style 'essay'` | Stylesheets did not install. Reinstall with `pip install -e .`. |
| `Could not start on port 8765` | Port in use: `webpage2pdf-server --port 8766`. |
| Output is nearly empty, with a warning | JavaScript-rendered or paywalled page. Save it from your browser and convert the file. |
| `403 … DataDome bot protection` (or Cloudflare, PerimeterX, Akamai, Imperva) | The site refuses scripted requests. See *When a site refuses the request* below. |
| Boxes instead of Chinese/Japanese text | Missing CJK fonts: `brew install --cask font-noto-serif-cjk-sc`. |

### When a site refuses the request

Some sites — most large news publishers among them — put a commercial bot wall
in front of their articles. The wall answers with `403` and a JavaScript
challenge instead of the page, and no combination of headers gets past it: it
wants a browser that runs the challenge. The tool now says exactly that, names
the wall, and stops rather than reporting a bare `HTTPError`.

Two ways through, both starting in a browser where the page already opens:

```bash
# 1. Save the page (File > Save Page As > "Web Page, Complete") and convert it
w2p ~/Downloads/article.html

# 2. Or lend the tool the session you already have
w2p --cookies cookies.txt https://example.com/article
```

`--cookies` reads three formats, which between them cover every exporter:
Netscape `cookies.txt` (what curl, wget and the *cookies.txt* browser
extensions write), the JSON array the other extensions write, and a single
`name=value; name=value` line copied out of a browser's network tab. The
cookies go to the page and to its images, so illustrations behind the same
session arrive too. Nothing is uploaded anywhere: the file is read locally and
sent only to the site it belongs to.

That is also the answer for a `401` — a page behind a login you have.

An unbranded `403` is more often hotlink protection, which wants the request to
come from the site's own pages; that one is retried automatically with a
referer before it is reported as a failure.

## Limits

- **JavaScript-rendered pages** return little text, because the tool reads the HTML the server sends rather than running scripts. Save the page in your browser first (⌘S, "Web Page, Complete") and convert the file — the tool warns you when a result looks suspiciously thin.
- **Paywalled articles** behave the same way. Save from a browser where you're logged in, or pass that browser's cookies with `--cookies`.
- **Bot walls** (DataDome, Cloudflare, PerimeterX, Akamai, Imperva) refuse a scripted request outright, and there is no header that changes their mind — the request has to carry a real browser session, or the page has to arrive as a saved file.
- **Saved pages with local images:** paste the file *path* rather than dragging the file in. A dropped file arrives without its `_files` folder, so those images can't be found.

## Tests

```bash
./.venv/bin/python tests/test_robustness.py   # 16 checks, extraction
./.venv/bin/python tests/test_pipeline.py     # 45 checks, formats, settings, refusals
./.venv/bin/python tests/test_realworld.py    # 28 checks, real production markup
```

`test_robustness.py` is sixteen checks covering unclosed tags, forty-deep div nesting, missing headings, unreachable images, nested tables, GB18030 encoding, mixed CJK/Arabic/Greek text, empty documents, and a hero image shipped once per responsive breakpoint beside a `print:hidden` recommendation rail. `tests/messy-page.html` is a realistic fixture — a page wrapped in nav, sidebar, ad slots, share buttons, a newsletter form, comments and a footer — for checking extraction by eye.

`test_pipeline.py` is forty-five checks over everything built on top: that each
format produces a file of the right shape, that the EPUB is structurally valid,
that Markdown keeps its tables, that standalone HTML has no external references,
that presets produce sane text blocks, that flags beat profiles and profiles beat
defaults, that the cache is actually consulted, and — against a local server
that refuses requests the way real ones do — that a bot wall, a login and a
rate limit are each reported as themselves rather than as a bare `HTTPError`,
and that a cookie file in any of the three exported formats reaches the site.
It isolates itself from your own `~/.config/webpage2pdf`, and touches no
network.

`test_realworld.py` runs extraction against unmodified, committed snapshots of
real pages — a Wikipedia article, a Python docs page, a 1990s-style
hand-written essay with no semantic tags at all, and an Aeon essay in modern
Next.js/Tailwind markup — rather than only hand-written synthetic cases. That
corpus found six real bugs no synthetic fixture happened to reproduce: a page
whose own `<html class>` coincidentally matched the furniture-stripping regex
and destroyed the entire document; a heading template that left every section
heading with no *sibling* of its own, so it was misjudged as empty and
deleted; scheme-relative image URLs resolving to a broken `file://` address on
any locally saved page — silently stripping every image, on exactly the
workaround this README recommends for JavaScript-rendered sites; an HTML
comment carrying internal cache metadata that got promoted into visible
article text; a hero image shipped once per responsive breakpoint and printed
twice back to back; and a `print:hidden` "recommended articles" rail the
content scorer pulled in with the article body. See
[`tests/fixtures/real-world/MANIFEST.md`](tests/fixtures/real-world/MANIFEST.md)
for the full story, sources, and licensing of each snapshot. It runs entirely
offline against the committed fixtures — no network access, no flakiness.
