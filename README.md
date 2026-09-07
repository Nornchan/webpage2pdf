# webpage2pdf

Turns web pages into clean A4 PDFs that read like typeset essays instead of screenshots of a website.

Saving a page from your browser keeps the site's screen layout and hands the pagination to a print engine that treats page-break rules as optional. You get sidebars, cookie banners, images sliced across two pages, and headings stranded at the foot of a page. This tool does something different: it works out which part of the page is actually the article, throws the rest away, and re-typesets the content from scratch for paper.

---

## Setup

**With Homebrew** (once the tap is published — see `packaging/RELEASE.md`):

```bash
brew install <you>/tap/webpage2pdf
```

This is the path worth preferring. Homebrew builds the virtualenv from its own
Python with `pango` as a declared dependency, which sidesteps the native-library
problem described under Troubleshooting rather than working around it at runtime.

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

Opens `http://127.0.0.1:8765`. Paste links or file paths one per line, or drop saved `.html` files onto the page. Finished PDFs land in `~/Documents/webpage2pdf` (override with `-o`) and download with one click. Nothing is uploaded anywhere — the server runs on your machine and is not reachable from the network.

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
| `--links plain\|endnotes\|keep` | Strip link styling, collect links as numbered endnotes, or keep them live |
| `--no-numbering` | Drop the automatic section and figure numbers |
| `--no-images` | Text only — much smaller files |
| `--no-url` / `--no-standfirst` | Trim the title block |
| `--keep-html FILE` | Also save the cleaned HTML, useful for checking what was removed |
| `-V`, `--version` | Print the version and exit |
| `--doctor` | Check the installation and report what is wrong |

---

## What it actually does

**1. Finds the article.** Every container on the page is scored on how much real prose it holds — paragraph count, text length, comma density — and penalised for link density, which is what separates an article from a list of headlines. Semantic tags (`<article>`, `<main>`) get a bonus. When a wrapper `div` and the article inside it score alike, the tighter one wins.

**2. Removes the furniture.** Two passes, deliberately. A broad sweep first for nav, footers, sidebars, cookie banners and modals; then, once the article is identified, a gentler sweep for share bars, newsletter forms, related-story rails, comments and ad slots. A section is spared if it turns out to be prose-heavy, so a genuine "Related concepts" heading in an explainer survives while a link rail does not.

Also handled: tables of contents, "edit" permalinks glued to headings, citation superscripts pointing at footnotes that aren't coming with us, and infobox sidebars.

**3. Rebuilds the structure.** Headings are re-levelled so the hierarchy is coherent — if a site starts its sections at `h3`, everything slides up so the top level is `h2`. Div-wrapped prose becomes real paragraphs, `<b>`/`<i>` become `<strong>`/`<em>`, definition lists become bullets, every site class and inline style is stripped, and captions orphaned in sibling divs are pulled into the `<figure>` they describe.

**4. Fixes the images.** Lazy-loaded sources are recovered from `data-src`, `data-original` and friends; `srcset` resolves to the highest-resolution candidate so print stays sharp. Tracking pixels, spacers and icons are dropped on size. Then the important part: **any image tall enough to overflow the text block is scaled down so it fits within a single page.** A 900×2400 diagram becomes 73mm wide rather than being cut in half.

**5. Typesets it.** A4, 25mm margins, serif body, justified with hyphenation, first-line indents, running header with the article title, page numbers, numbered sections and figures.

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
| Boxes instead of Chinese/Japanese text | Missing CJK fonts: `brew install --cask font-noto-serif-cjk-sc`. |

## Limits

- **JavaScript-rendered pages** return little text, because the tool reads the HTML the server sends rather than running scripts. Save the page in your browser first (⌘S, "Web Page, Complete") and convert the file — the tool warns you when a result looks suspiciously thin.
- **Paywalled articles** behave the same way. Save from a browser where you're logged in.
- **Saved pages with local images:** paste the file *path* rather than dragging the file in. A dropped file arrives without its `_files` folder, so those images can't be found.

## Tests

```bash
./.venv/bin/python tests/test_robustness.py
```

Fifteen checks covering unclosed tags, forty-deep div nesting, missing headings, unreachable images, nested tables, GB18030 encoding, mixed CJK/Arabic/Greek text, and empty documents. `tests/messy-page.html` is a realistic fixture — a page wrapped in nav, sidebar, ad slots, share buttons, a newsletter form, comments and a footer — for checking extraction by eye.
