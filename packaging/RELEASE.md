# Releasing, and the Homebrew tap

## Status: done through v0.1.1

- Source repo: [github.com/Nornchan/webpage2pdf](https://github.com/Nornchan/webpage2pdf), public
- Current release: [v0.1.1](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.1) — a Homebrew packaging fix; [v0.1.0](https://github.com/Nornchan/webpage2pdf/releases/tag/v0.1.0) is still tagged for history
- Tap: [github.com/Nornchan/homebrew-tap](https://github.com/Nornchan/homebrew-tap), public, formula tracks the latest release
- Install, verified end to end from a genuinely fresh, untapped, untrusted
  machine state:

  ```bash
  brew install Nornchan/tap/webpage2pdf
  ```

- The 0.1.0 → 0.1.1 upgrade itself verified with `brew upgrade webpage2pdf`
  against a real prior install, not just a fresh one.
- `brew test`, `brew audit --strict --online`: both exit 0, no findings.

The steps below are the ones that got it there. Sections 1–2 and "Refreshing
dependency pins" are the ones you'll actually repeat for a future release;
"Create the tap" is a one-time action, done, kept here only in case the tap
ever needs to be recreated from scratch.

## Changelog

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

First packaged release. Installable via pip (`webpage2pdf` / `w2p` /
`webpage2pdf-server` entry points) or Homebrew; bundled Literata typography
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
