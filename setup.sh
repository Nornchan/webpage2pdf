#!/usr/bin/env bash
# One-time setup for webpage2pdf on macOS.
#   bash setup.sh
set -e

cd "$(dirname "$0")"

echo "→ Checking for Homebrew…"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed. Install it first:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 1
fi

BREW_PREFIX="$(brew --prefix)"

# WeasyPrint renders text through Pango, loaded at runtime via dlopen().
echo "→ Installing the text-rendering libraries (pango)…"
brew install pango

# Pick the interpreter to build the venv from.
#
# Two traps to avoid:
#   * Anaconda's python searches /opt/anaconda3/lib and never finds Homebrew's
#     libraries, which is the "cannot load library 'libpango-1.0-0'" error.
#   * Apple's /usr/bin/python3 is protected by SIP, which *strips*
#     DYLD_FALLBACK_LIBRARY_PATH on launch — so the usual fix silently fails.
#
# Homebrew's own python has neither problem, so we prefer it.
PYTHON=""
for candidate in "$BREW_PREFIX/bin/python3" /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
done

if [ -z "$PYTHON" ]; then
  echo "→ Installing Homebrew's Python (more reliable than Anaconda here)…"
  brew install python
  for candidate in "$BREW_PREFIX/bin/python3" /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
  done
fi

if [ -z "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
  echo "  ! Falling back to $PYTHON"
  case "$PYTHON" in
    *conda*) echo "  ! This is an Anaconda Python; the library path fix will be applied automatically." ;;
  esac
else
  echo "→ Using $PYTHON"
fi

echo "→ Creating a virtual environment in .venv…"
rm -rf .venv
"$PYTHON" -m venv .venv

echo "→ Installing Python packages…"
./.venv/bin/pip install --upgrade pip --quiet
./.venv/bin/pip install -r requirements.txt --quiet

# Belt and braces: _bootstrap.py sets this at runtime too, but exporting it here
# means the verification below tests the same conditions the tool will run under.
export DYLD_FALLBACK_LIBRARY_PATH="$BREW_PREFIX/lib:${DYLD_FALLBACK_LIBRARY_PATH:-$HOME/lib:/usr/local/lib:/lib:/usr/lib}"

echo "→ Verifying…"
if ./.venv/bin/python html2pdf.py --doctor; then
  :
else
  echo "Setup finished, but the check above found a problem."
  exit 1
fi

echo "→ Running a real conversion as a final test…"
./.venv/bin/python html2pdf.py tests/messy-page.html -o /tmp/webpage2pdf-selftest.pdf --quiet \
  && echo "   Wrote /tmp/webpage2pdf-selftest.pdf"

cat <<DONE

Setup complete.

  Web app:      ./.venv/bin/python server.py
  Command line: ./.venv/bin/python html2pdf.py <url-or-file>
  Troubleshoot: ./.venv/bin/python html2pdf.py --doctor

Optional shortcut, so you can type \`topdf <url>\` from anywhere:

  echo "alias topdf=\\"'$(pwd)/.venv/bin/python' '$(pwd)/html2pdf.py'\\"" >> ~/.zshrc
  source ~/.zshrc

DONE
