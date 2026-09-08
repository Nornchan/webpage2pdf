# Real-world fixtures

Unmodified HTML snapshots of real pages, fetched once and committed, so
extraction is tested against actual production markup rather than only
hand-written synthetic cases. `test_robustness.py` and `test_pipeline.py`
cover the code's own edge cases well; nothing before this exercised what
real templating systems actually emit.

The pattern — snapshot real pages, commit the HTML, assert against the
frozen copy — is the same one Mozilla's Readability.js test corpus uses.
A live fetch in a test suite is flaky by nature (redesigns, rate limits,
consent walls) and would break CI on someone else's unrelated change.

Each snapshot is included solely as inert input to an automated test; none
of it is served, redistributed as content, or presented to an end user.

| File | Source | Fetched | Chosen for | Bug it caught |
|---|---|---|---|---|
| `wikipedia-intermodal-container.html` | [en.wikipedia.org/wiki/Intermodal_container](https://en.wikipedia.org/wiki/Intermodal_container) (CC BY-SA 4.0) | 2026-09-07 | MediaWiki's Vector 2022 skin: heavy nav/sidebar, infoboxes, citation superscripts, a TOC, headings individually wrapped in their own `<div>`, HTML comments carrying internal cache metadata | Four. See below. |
| `python-docs-tutorial.html` | [docs.python.org/3/tutorial/introduction.html](https://docs.python.org/3/tutorial/introduction.html) (PSF License) | 2026-09-07 | Sphinx-generated docs: code blocks, nested lists, footnotes, a real `<main>`/`<article>` structure | None — kept as a clean-case control so a future change that breaks *this* one is easy to tell apart from one that only affects adversarial markup. |
| `paulgraham-life-is-short.html` | [paulgraham.com/vb.html](http://www.paulgraham.com/vb.html) | 2026-09-07 | 1990s-era hand-written markup: nested layout `<table>`s, no semantic tags at all, no `<article>`/`<main>` to anchor scoring on | Adversarial control for the scoring heuristic — confirms it can still find the article with zero structural help. |
| `aeon-persuasion-manipulation.html` | [aeon.co/ideas/how-to-tell-the-difference-between-persuasion-and-manipulation](https://aeon.co/ideas/how-to-tell-the-difference-between-persuasion-and-manipulation) | 2026-09-08 | Next.js / Tailwind component markup: the hero image shipped once per breakpoint (two `<img>`, same asset), a `print:hidden` "more from Aeon" rail of recommended-article cards sitting inside `<main>` beside the article, HTML tags stuffed into an `alt` attribute | Two. See below. |

## Bugs the Wikipedia fixture caught

All four were real, silent-data-loss or silent-content-corruption defects,
found only by running extraction against this page — none were reachable
from the synthetic fixtures, because none of the synthetic HTML happened to
reproduce the specific real-world markup pattern each one depends on.

1. **The entire document was destroyed.** `<html class="... main-menu-disabled ... vector-toc-available ...">` — ordinary client-side feature-flag classes — matched the furniture-stripping regex on the substrings `-menu-` and `-toc-`, and the sweep had no floor protecting a large, prose-heavy ancestor (or the document root itself) from a coincidental match. Fixed in `_strip_global`: `<html>`/`<body>` are never eligible, and the same "spared if prose-heavy" guard already used one pass later now applies here too.

2. **Every section heading was deleted.** The skin wraps each heading alone in `<div class="mw-heading">`; once the div's other child (an edit-section link) is correctly stripped as chrome, the heading has no *sibling* left, even though the section's paragraphs immediately follow the wrapper. `_remap_headings`'s "a heading with nothing under it is a label" check used sibling-only traversal (`find_next_sibling`). Fixed by switching to document-order traversal (`find_next`).

3. **Every image silently vanished from a locally saved copy.** Wikipedia's image URLs are scheme-relative (`//upload.wikimedia.org/...`). Resolving one against a `file://` base — which is exactly what every locally saved page uses, the tool's own documented workaround for JavaScript-rendered or paywalled pages — produces a nonsensical `file://upload.wikimedia.org/...` URL that `_download_image` then fails to open as a local path, with the failure silently swallowed. Fixed with a shared `_resolve_url()` helper that always resolves scheme-relative references to `https:`.

4. **Internal debug metadata became visible article text.** An HTML comment carrying a Parsoid cache key (`<!-- Post-processing cache key enwiki:postproc-parsoid-pcache:... -->`) was promoted into a real, visible `<p>` in the output and counted toward the reported word total — because `bs4.Comment` is a subclass of `NavigableString`, so the "loose text needs a paragraph" pass in `_promote_text_blocks` couldn't tell a comment from prose. Fixed by stripping every `Comment` node in `_strip_global`, before any later pass can make the same mistake.

## Bugs the Aeon fixture caught

Both produced visible junk in the PDF rather than silent loss — an Aeon
essay of ~1,350 words came out as nine pages.

1. **The hero image printed twice, back to back.** Aeon ships the lead
   image once per breakpoint — a mobile `<img>` and a desktop `<img>`, same
   asset — and nothing in the pipeline collapsed responsive image variants,
   so both were downloaded and rendered one after the other. The mobile
   copy also carried raw HTML (`<p>…<em>…</em></p>`) in its `alt`, which
   surfaced as escaped tags in the caption. Fixed with a `seen_src` set in
   `_process_images`: the first occurrence of a resolved source wins, the
   rest are dropped.

2. **The "more from Aeon" rail landed in the article.** The recommended-
   article cards — six of them, each with its own thumbnail and teaser —
   sit in a `<div class="print:hidden">` that is a sibling of the article
   *inside* `<main>`, and the scorer picks `<main>`. Fixed in
   `_strip_global` by honouring the page's own print-suppression classes
   (`print:hidden`, `d-print-none`, `hidden-print`, …): when the whole job
   is to render for print, "hide this when printing" is the most reliable
   furniture signal there is. A node that is essentially just an image is
   spared, so a hero the site swaps for a print-specific copy is left for
   the de-dup and size filters to judge.

## Refreshing a fixture

Real pages change. If the extractor legitimately needs new coverage, re-fetch
with a real user agent, update this table's fetch date, and re-run
`test_realworld.py` — it will tell you exactly which assertion the new
snapshot breaks.
