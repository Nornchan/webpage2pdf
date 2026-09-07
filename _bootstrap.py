"""
_bootstrap.py — make WeasyPrint find its native libraries on macOS.

The problem
-----------
WeasyPrint doesn't bundle its text engine. It loads Pango, Cairo and friends at
runtime with dlopen(). Homebrew installs those under /opt/homebrew/lib (Apple
Silicon) or /usr/local/lib (Intel), but dyld does not search either by default.
Under Anaconda it's worse: the interpreter looks in /opt/anaconda3/lib, so you
get

    OSError: cannot load library 'libpango-1.0-0'

even though `brew install pango` succeeded.

Why an environment variable isn't enough
----------------------------------------
The fix is DYLD_FALLBACK_LIBRARY_PATH, but dyld reads it *once, at process
start*. Setting os.environ from inside a running Python is too late — dlopen
will not see it. So we set the variable and re-exec ourselves exactly once,
guarded by a sentinel so we can't loop.

The upshot: `python3 html2pdf.py …` just works, with no shell configuration and
no wrapper script for the user to remember.
"""

from __future__ import annotations

import glob
import os
import sys

SENTINEL = "W2P_LIBPATH_READY"

# Where Homebrew puts things, newest layout first.
CANDIDATE_DIRS = (
    "/opt/homebrew/lib",           # Apple Silicon
    "/usr/local/lib",              # Intel
    "/opt/homebrew/opt/pango/lib",
    "/usr/local/opt/pango/lib",
    "/opt/local/lib",              # MacPorts
)

# dyld's built-in default, which we must preserve when we override the variable.
DEFAULT_FALLBACK = (os.path.expanduser("~/lib"), "/usr/local/lib", "/lib", "/usr/lib")


def _dirs_containing_pango() -> list[str]:
    return [d for d in CANDIDATE_DIRS
            if os.path.isdir(d) and glob.glob(os.path.join(d, "libpango-1.0*.dylib"))]


def ensure_native_libs() -> None:
    """
    Point dyld at Homebrew's libraries, re-executing once if needed.

    No-op on Linux and Windows, and on macOS when the libraries are already
    reachable. Safe to call more than once.
    """
    if sys.platform != "darwin" or os.environ.get(SENTINEL):
        return

    # Mark first: even if we bail out below, a child process shouldn't retry.
    os.environ[SENTINEL] = "1"

    found = _dirs_containing_pango()
    if not found:
        return  # Pango isn't installed; the import error will say so clearly.

    current = [p for p in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "").split(":") if p]
    missing = [d for d in found if d not in current]
    if not missing:
        return  # already reachable

    merged = missing + current + [d for d in DEFAULT_FALLBACK if d not in current]
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(dict.fromkeys(merged))

    # Re-exec so dyld picks the variable up at start-up.
    if not sys.argv or not sys.argv[0] or not os.path.isfile(sys.argv[0]):
        return  # a REPL or -c invocation; don't hijack it
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except OSError:
        pass  # fall through and let the import raise a real error


def diagnose() -> int:
    """Print an environment report. Backs `html2pdf.py --doctor`."""
    ok = True
    print("\n  webpage2pdf environment check")
    print("  " + "-" * 52)
    print(f"  platform            {sys.platform}")
    print(f"  python              {sys.version.split()[0]}")
    print(f"  interpreter         {sys.executable}")

    if "anaconda" in sys.executable.lower() or "miniconda" in sys.executable.lower():
        print("                      (Anaconda — needs the library path fix below)")

    if sys.platform == "darwin":
        found = _dirs_containing_pango()
        if found:
            print(f"  pango found in      {', '.join(found)}")
        else:
            ok = False
            print("  pango found in      NOT FOUND  →  run: brew install pango")
        print(f"  DYLD fallback path  {os.environ.get('DYLD_FALLBACK_LIBRARY_PATH') or '(unset)'}")

    for module in ("weasyprint", "bs4", "lxml", "requests", "PIL"):
        try:
            mod = __import__(module)
            version = getattr(mod, "__version__", "ok")
            print(f"  {module:<19} {version}")
        except Exception as exc:
            ok = False
            print(f"  {module:<19} FAILED — {type(exc).__name__}: {str(exc)[:60]}")

    if ok:
        print("\n  All good.\n")
    else:
        print("\n  Something's missing. On macOS the usual fix is:")
        print("      brew install pango")
        print("      export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH")
        print("  If you're on Anaconda, rebuilding the venv from Homebrew's Python")
        print("  is more reliable:")
        print("      brew install python")
        print("      rm -rf .venv && /opt/homebrew/bin/python3 -m venv .venv")
        print("      ./.venv/bin/pip install -r requirements.txt\n")
    return 0 if ok else 1
