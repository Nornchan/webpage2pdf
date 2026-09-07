# Releasing, and standing up the Homebrew tap

Everything here is outward-facing — it creates public repositories and uploads
artefacts — so none of it has been run for you. The formula in this directory is
complete and `brew style`-clean apart from the placeholder `sha256`, which
cannot be computed until a tarball exists.

## 1. Publish the source repository

```bash
gh repo create webpage2pdf --public --source=. --remote=origin --push
git push origin v0.1.0
```

## 2. Cut the release and get the checksum

```bash
gh release create v0.1.0 --generate-notes
curl -sL https://github.com/<you>/webpage2pdf/archive/refs/tags/v0.1.0.tar.gz \
  | shasum -a 256
```

Paste that digest over `replace_with_tarball_sha256` in `webpage2pdf.rb`, and
replace `norachan` in the `homepage`, `url` and `head` fields if your GitHub
username differs.

## 3. Create the tap

A tap is just a repository named `homebrew-<something>`:

```bash
gh repo create homebrew-tap --public --clone
mkdir -p homebrew-tap/Formula
cp packaging/webpage2pdf.rb homebrew-tap/Formula/
cd homebrew-tap && git add -A && git commit -m "webpage2pdf 0.1.0" && git push
```

## 4. Verify before announcing it

```bash
brew tap <you>/tap
brew install --build-from-source <you>/tap/webpage2pdf
brew test <you>/tap/webpage2pdf
brew audit --strict --online <you>/tap/webpage2pdf
```

`brew test` runs the `test do` block in the formula: it converts a page wrapped
in nav, sidebar and footer, then asserts the PDF is real, the article survived
and the footer did not. All six of its assertions have been checked against the
working tool, so a failure means the packaging is wrong, not the test.

## 5. Confirm the install path skips the bootstrap

The main reason to package this properly is that the Homebrew venv is built from
Homebrew's own Python with `pango` as a declared dependency, so
`_bootstrap.ensure_native_libs()` finds nothing to fix and never re-execs. Source
installs still need it. Check:

```bash
brew install <you>/tap/webpage2pdf
webpage2pdf --doctor        # should report pango found, all packages OK
```

## Refreshing dependency pins later

The `resource` stanzas were generated from a known-good virtualenv. To regenerate
after a dependency bump:

```bash
brew update-python-resources Formula/webpage2pdf.rb
```

## Known deviations from homebrew-core

Fine for a personal tap; fix before ever proposing it to homebrew-core.

- `Style/Documentation` — `brew style` wants a class doc comment on a standalone
  file. Formulae inside a tap are exempt via the tap's own rubocop config.
- homebrew-core requires notability (stars, watchers, forks) that a new project
  will not have. The tap is the right home for now.
