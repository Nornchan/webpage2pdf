# Releasing, and the Homebrew tap

## Status: done through v0.1.6

- Source repo: [github.com/Nornchan/webpage2pdf](https://github.com/Nornchan/webpage2pdf), public
- Current release: [v0.1.6](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.6); v0.1.0–v0.1.5 are still tagged for history
- Tap: [github.com/Nornchan/homebrew-tap](https://github.com/Nornchan/homebrew-tap), public, formula tracks the latest release
- Install, verified end to end from a genuinely fresh, untapped, untrusted
  machine state:

  ```bash
  brew install Nornchan/tap/webpage2pdf
  ```

- **Not published to plain PyPI.** `webpage2pdf` there is a completely
  unrelated project by a different author. Never write `pip install
  webpage2pdf` anywhere in this repo, its docs, or a release note — the only
  supported pip install is `pip install -e .` from a source checkout. This bit
  a real release once already (v0.1.2's own notes, and shipped code in
  `_bootstrap.repair()`); see the v0.1.3 changelog entry.
- Real upgrades verified with `brew upgrade webpage2pdf` against actual prior
  installs each time (0.1.0 → 0.1.1, then 0.1.1 → 0.1.3), not just fresh
  installs.
- `brew test`, `brew audit --strict --online`: both exit 0, no findings, as of
  v0.1.3.

The steps below are the ones that got it there. Sections 1–2 and "Refreshing
dependency pins" are the ones you'll actually repeat for a future release;
"Create the tap" is a one-time action, done, kept here only in case the tap
ever needs to be recreated from scratch.

## Changelog

### [v0.1.6](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.6) — 2026-09-11

Removes the "related stories" rails that a component-framework site leaks into
the article. A New York Times piece saved from the browser and converted came
out **23 pages and 14.2 MB**, of which **17 pages were recirculation**: a
`Related Content` block holding `More in Europe` and `Editors' Picks`, each a
list of headline links with a full-bleed photograph, and each promoted into the
table of contents as though it were a chapter of the article.

- **Furniture removal no longer depends on the site naming its furniture.**
  Every sweep in `extractor.py` matched on `id`/`class`/`role` tokens. NYT is
  built on Emotion, so every class on the page is a hash — `css-2ypnkk`,
  `css-16p55jy` — and the rails carried no token any pattern could see. The
  one semantic attribute on the block, `data-testid="recirculation"`, is not
  among the attributes `_matches` reads, and the `id` that is
  (`recirculation-title`) sits on the heading alone, not the rail.
- **So the heading is the signal.** `_strip_recirculation` matches heading
  *text* against `RECIRC_HEADING` — "Related Content", "More in Europe",
  "Editors' Picks", "You might also like", "Most read" and the rest. That only
  nominates a candidate. `_is_link_rail` then decides on shape: at least half
  the text inside anchors, and no paragraph over 120 characters carrying
  sentence punctuation. A genuine prose section titled "Related concepts"
  fails the shape test and survives untouched — as does a Wikipedia "See also"
  list, whose heading the pattern deliberately does not name.
- **Two layouts, one pass.** From a matching heading it climbs to the
  outermost ancestor that still holds nothing but link text, which is what
  removes NYT's wrapper and both nested rails in one go; the climb stops at
  the first ancestor containing real prose, which is what keeps the article
  safe. Where a rail has no wrapper, it falls back to the heading plus the run
  of siblings under it, up to the next heading of the same or higher rank.

Guarded by three new synthetic cases in `test_robustness.py` — a hashed-class
rail, a flat rail with no wrapper, and a prose section whose heading matches
but whose shape does not — each also asserting the article itself is intact.
Full suite 92 checks (19 + 45 + 28), all green.

Verified against the actual saved page, not only the reproduction: it now
extracts 1,728 words across the article's own 4 sections and renders **6
pages**, where before the fix the same file gave 2,005 words across 7 sections
and 23 pages. All four committed real-world fixtures extract byte-identically
to v0.1.5 — same word counts, same section counts — so nothing else moved.

Verified end to end: real upgrade from an actual 0.1.5 install
(`nornchan/tap/webpage2pdf 0.1.5 -> 0.1.6`, built from source in 2m03s);
`brew test` and `brew audit --strict --online` both exit 0, no findings; the
installed binary renders the NYT file at 6 pages and still converts an
unwalled page unchanged (a live Wikipedia article, 59 pages / 40 images).
The formula's `test do` block gained a matching assertion, so a future
packaging change that regresses this fails `brew test` — every one of its
four new assertions was checked against the working tool before committing.

Note for anyone reproducing the original 23-page PDF: a browser's "Web Page,
Complete" save writes a companion `<name>_files/` folder next to the HTML
holding every image. Convert the HTML without that folder beside it and the
PDF comes out correct but illustration-free — which is why the runs above
report 0 images.

### [v0.1.5](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.5) — 2026-09-10

Fixes what a site's bot wall used to look like from the command line. A New
York Times URL reported `HTTPError: 403 Client Error: Forbidden`, which names
no cause, suggests no fix, and reads like a bug in the tool. It is not: the
article sits behind DataDome, which serves a JavaScript challenge to anything
that is not a browser running it.

- **Refusals are now their own kind of failure.** `extractor.FetchBlocked`
  covers 401, 403, 429 and 451, recognises the five commercial walls
  (DataDome, Cloudflare, PerimeterX, Akamai, Imperva) from what they serve
  with the refusal, and carries a message that names the wall and the two
  ways round it. The CLI prints that message as written; the web app shows
  it in the failed row.
- **`--cookies FILE`.** Lends the run the browser session you already have,
  for a page behind a login or a wall your browser has already cleared.
  Netscape `cookies.txt`, the JSON array most extensions export, and a
  pasted `Cookie:` header line are all read; the cookies go to the page and
  its images. Session cookies (expiry `0`) are kept rather than discarded as
  expired, which is the whole point of them. A bad path fails before the
  first request rather than once per source.
- **A fuller, honest request.** `Sec-Fetch-*`, `Upgrade-Insecure-Requests`
  and a proper `Accept` go out with the page fetch, and images now carry the
  page as their referer — hotlink protection was silently costing
  illustrations. An unbranded 403 is retried once with a referer before it
  is reported.
- **A 404 is still a 404.** Only the refusal statuses take the new path.

Thirteen new checks in `test_pipeline.py`, against a local server that refuses
requests the way the real ones do — no network, and no dependence on which
sites happen to be walled this week.

Verified end to end: real upgrade from an actual 0.1.4 install
(`nornchan/tap/webpage2pdf 0.1.4 -> 0.1.5`, built from source in 3m25s);
`brew test` and `brew audit --strict --online` both exit 0; the installed
binary reports the NYT URL that prompted this as a named DataDome refusal
with both routes round it, and still converts an unwalled page (a Wikipedia
article, 39 pages / 16 images) unchanged.

### [v0.1.4](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.4) — 2026-09-08

Optimises extraction for aeon.co, and closes two general classes of defect
that a modern component-framework site exposes. An Aeon essay of ~1,350
words was coming out as a nine-page PDF.

- **The hero image printed twice, back to back.** Sites built for
  responsive breakpoints ship the lead image once per breakpoint — a
  separate `<img>` for mobile and for desktop, same asset — and nothing
  collapsed those variants. Fixed with a `seen_src` set in
  `_process_images`: first resolved source wins, later duplicates are
  dropped. Also covers `<picture>` and a hero duplicated inside and outside
  the article wrapper. (The Aeon mobile copy additionally carried raw HTML
  in its `alt`, which had been surfacing as escaped `<p>` tags in the
  caption — gone with the duplicate.)
- **The "more from this site" rail landed in the article.** Aeon's
  recommended-article cards — six of them, each with a thumbnail and teaser
  — sit in a `<div class="print:hidden">` that is a sibling of the article
  *inside* `<main>`, and the content scorer picks `<main>`. Fixed in
  `_strip_global` by honouring the page's own print-suppression classes
  (`print:hidden`, `d-print-none`, `hidden-print`, `no-print`, …): when the
  whole job is rendering for print, "hide this when printing" is the most
  reliable furniture signal there is. A node that is essentially just an
  image is spared, so a hero the site swaps for a print-specific copy is
  left for the de-dup and size filters to judge.

Regression-guarded three ways: a new committed fixture
`tests/fixtures/real-world/aeon-persuasion-manipulation.html` with five
assertions in `test_realworld.py`; a synthetic end-to-end case in
`test_robustness.py` exercising both fixes with a real local image; and a
`print:hidden`-rail assertion in the formula's `test do` block, so a
`brew test` fails if a future packaging change regresses it. Full suite
76 checks (16 + 32 + 28), all green; CI runs it on Linux and macOS on
every push.

Verified end to end: real upgrade from an actual 0.1.3 install
(`nornchan/tap/webpage2pdf 0.1.3 -> 0.1.4`, built from source);
`brew test` and `brew audit --strict --online` both exit clean; a live
aeon.co conversion with the installed binary now renders 4 pages / 1
image (was 9 pages / 8 images).

### [v0.1.3](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.3) — 2026-09-08

Fixes a real supply-chain risk in `--doctor --fix`. Its repair function had a
fallback, for the normal case of a Homebrew or packaged install with no local
source checkout, that ran `pip install webpage2pdf` outright. `webpage2pdf` is
already taken on PyPI by a completely unrelated project by a different author
— this project has never been published there and has no supported plain-pip
install path at all. Anyone hitting a broken venv on such an install and
running `--doctor --fix` would have silently installed the wrong package.

Found while double-checking v0.1.2's own release notes for accuracy: they had
"pip install webpage2pdf" as an alternate install method, written without
verifying it first. Corrected directly on that release once found.

Fixed by never guessing an install target in that branch: it now prints both
real install methods (`brew reinstall`, `pip install -e` from a fresh
checkout) and does not run pip at all. Verified directly against the exact
directory depth a real Homebrew install has (no `pyproject.toml` three levels
up) to confirm the new message fires and no pip command is constructed.

Also: the formula in the tap had been left pointing at v0.1.1's tarball —
the v0.1.2 release cycle got interrupted by investigating CI failures before
circling back to update it. Caught and fixed in the same pass.

Verified end to end: real upgrade from an actual 0.1.1 install
(`nornchan/tap/webpage2pdf 0.1.1 -> 0.1.3`); `brew test` and
`brew audit --strict --online` both exit clean.

### [v0.1.2](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.2) — 2026-09-08

Fixes a real installation-breaking bug on Python 3.10 via pip.
`profiles.py` imported `tomllib` unconditionally, but `tomllib` is stdlib only
from Python 3.11. `pyproject.toml` claims `requires-python >= 3.10` and CI
matrices 3.10, but the package could not actually be imported there — every
command failed immediately with `ModuleNotFoundError: No module named
'tomllib'`. Fixed with the standard fallback (`tomli` on Python < 3.11), added
as a conditional dependency. Verified against a real Python 3.10.2
interpreter, not just reasoned about: the backport activates there and all 47
tests pass; a real 3.13/3.14 interpreter still correctly uses the stdlib
module.

Also fixes the CI lint job, which had no `zsh` installed on its
`ubuntu-latest` runner and so failed checking the zsh completion file's
syntax — an oversight in the workflow itself, not a defect in the completion
file.

Found while verifying that the newly added GitHub release badge on the README
renders correctly: it did — what it rendered was "CI - failing," a real,
accurate signal, not a false one.

### [v0.1.1](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.1) — 2026-09-07

Homebrew packaging fix. The formula did not actually build from source:

- Pillow's sdist build needs `cmake`/`ninja` on `PATH`; without them declared,
  pip tried to bootstrap both from source inside Homebrew's sandboxed build
  environment and failed with an unrelated-looking `lipo` error against a
  shim script rather than a real binary.
- Every library dependency was declared (`jpeg-turbo`, `freetype`, ...) but
  not `pkg-config` itself, the tool that actually reads their `.pc` files, so
  Pillow's build could not find libjpeg.

Both fixed with `depends_on ... => :build`. Also renamed the
`typing_extensions` resource to `typing-extensions` to match its PyPI package
name (`brew audit --strict`), and corrected a false claim in the formula,
README and this file that Homebrew's `pango` dependency eliminates the
`DYLD_FALLBACK_LIBRARY_PATH` re-exec in `_bootstrap.py`. It does not — dyld's
default search path never includes `/opt/homebrew/lib` regardless of how
pango was installed; what the dependency actually buys is that the fix always
finds a correctly-linked library and always succeeds.

Verified end to end: `brew install` from a genuinely fresh, untapped,
untrusted machine state; `brew upgrade webpage2pdf` against a real prior
0.1.0 install (not just a fresh install); `brew test` and
`brew audit --strict --online` both exit clean.

### [v0.1.0](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.0) — 2026-09-07

First packaged release. Installable via `pip install -e .` from a source
checkout (`webpage2pdf` / `w2p` / `webpage2pdf-server` entry points) or
Homebrew — not from plain PyPI, see the Status note above; bundled Literata typography
with a full OpenType layer; four output formats (PDF/HTML/EPUB/Markdown);
seven profiles; six page presets; a fetch cache; parallel batch conversion;
CI across Linux and macOS; and four real, silent extraction bugs found and
fixed by testing against actual production pages (Wikipedia, Python docs, and
1990s hand-written HTML) rather than only synthetic fixtures.

## 1. Publish the source repository

```bash
gh repo create webpage2pdf --public --source=. --remote=origin --push
git push origin vX.Y.Z
```

## 2. Cut the release and get the checksum

```bash
gh release create vX.Y.Z --generate-notes
curl -sL https://github.com/Nornchan/webpage2pdf/archive/refs/tags/vX.Y.Z.tar.gz \
  | shasum -a 256
```

Paste that digest over the `sha256` line in `webpage2pdf.rb`, and bump the
`url` and `version` to match.

## 3. Create the tap — one-time, already done

A tap is just a repository named `homebrew-<something>`:

```bash
gh repo create homebrew-tap --public --clone
mkdir -p homebrew-tap/Formula
cp packaging/webpage2pdf.rb homebrew-tap/Formula/
cd homebrew-tap && git add -A && git commit -m "webpage2pdf 0.1.0" && git push
```

A future formula update goes straight to `homebrew-tap`'s `Formula/webpage2pdf.rb`
— see "Refreshing dependency pins" below — not through this step again.

## 4. Verify before announcing it

```bash
brew install Nornchan/tap/webpage2pdf
brew test Nornchan/tap/webpage2pdf
brew audit --strict --online Nornchan/tap/webpage2pdf
```

No `--build-from-source` needed: the formula ships no bottle, so every install
already builds from source.

One thing worth knowing if you're on a newer Homebrew: `brew tap user/repo`
alone can refuse to load an untrusted third-party tap's formula and ask for
`brew trust --tap user/repo` first. `brew install user/repo/formula` does not
hit this — it auto-trusts the formula it was explicitly told to install, even
from a completely untapped, untrusted state. Confirmed by wiping local tap and
trust state entirely and re-running the command above from scratch.

`brew test` runs the `test do` block in the formula: it converts a page wrapped
in nav, sidebar and footer, then asserts the PDF is real, the article survived
and the footer did not, and (as of the current formula) that all four output
formats produce a file of the right shape and the CLI reads from stdin and
writes to stdout. Every one of those assertions has been checked against the
working tool directly, so a failure means the packaging is wrong, not the test.

Building from source genuinely needs to succeed, not just parse: the first
attempt at this formula failed twice on real gaps — Pillow's sdist build needs
`cmake`/`ninja` on `PATH` or pip tries to bootstrap them from source inside
Homebrew's sandboxed build environment and fails in a way that has nothing to
do with the actual error; and every *library* dependency (jpeg-turbo, etc.) was
declared but not `pkg-config`, the tool that actually reads their `.pc` files.
Both are now `depends_on ... => :build` in the formula. `brew style` alone
would never have caught either one.

## 5. Confirm pango is found reliably

The Homebrew venv is built from Homebrew's own Python with `pango` as a
declared dependency. `_bootstrap.ensure_native_libs()`'s
DYLD_FALLBACK_LIBRARY_PATH re-exec still runs — dyld's default search path
never includes `/opt/homebrew/lib`, Homebrew build or not, confirmed by
tracing it against an actual Homebrew-installed interpreter — but it now
always finds a correctly-linked pango and always succeeds, rather than
depending on you having separately run `brew install pango` and built the
venv from that same Homebrew Python rather than Anaconda's. Check:

```bash
webpage2pdf --doctor        # should report pango found, all packages OK
```

## Refreshing dependency pins later

The `resource` stanzas were generated from a known-good virtualenv. To regenerate
after a dependency bump:

```bash
brew update-python-resources Formula/webpage2pdf.rb
```

Keep `packaging/webpage2pdf.rb` in the main repo as the source of truth, copy
the result to `homebrew-tap/Formula/webpage2pdf.rb`, and rebuild from scratch
(not `--build-from-source` on top of a cached bottle — there is no bottle) to
confirm the new pins actually install before pushing.

## Known deviations from homebrew-core

Fine for a personal tap; fix before ever proposing it to homebrew-core.

- `Style/Documentation` — `brew style` wants a class doc comment on a standalone
  file. Formulae inside a tap are exempt via the tap's own rubocop config, and
  confirmed clean when checked from inside a real `Formula/` directory.
- homebrew-core requires notability (stars, watchers, forks) that a new project
  will not have. The tap is the right home for now.
