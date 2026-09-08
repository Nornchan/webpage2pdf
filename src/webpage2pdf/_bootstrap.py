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
    argv = _reexec_argv()
    if argv is None:
        return  # a REPL or -c invocation; don't hijack it
    try:
        os.execv(sys.executable, argv)
    except OSError:
        pass  # fall through and let the import raise a real error


def _reexec_argv() -> list[str] | None:
    """
    Rebuild the command line that started us, preserving its *form*.

    This is subtler than `[sys.executable] + sys.argv`. Under `python -m pkg`,
    runpy rewrites sys.argv[0] to the path of the package's __main__.py, so
    naively re-execing sys.argv runs that file as a plain script — which drops
    __package__ and makes every relative import inside the package fail with

        ImportError: attempted relative import with no known parent package

    sys.modules["__main__"].__spec__ is set only for the -m form, and its
    `parent` names the package, so we can detect the case and re-exec as -m.

    Returns None when there is nothing sensible to re-exec (a REPL, `-c`, or a
    stdin script), in which case the caller leaves the process alone.
    """
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    if spec is not None:
        # Launched as `python -m <parent>`; keep it that way.
        module = spec.parent or spec.name
        if module:
            return [sys.executable, "-m", module, *sys.argv[1:]]

    if sys.argv and sys.argv[0] and os.path.isfile(sys.argv[0]):
        return [sys.executable, *sys.argv]

    return None


def _run(command: list[str]) -> bool:
    """Run one remedial command, showing it first."""
    import subprocess
    print("      $ " + " ".join(command))
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        print(f"      failed to start: {exc}")
        return False
    return result.returncode == 0


def repair() -> int:
    """
    Attempt the fixes `diagnose` would otherwise only recommend.

    Backs `--doctor --fix`. Every command is printed before it runs, because
    this installs software: you should be able to see what it did afterwards,
    and run the same thing by hand if you would rather.
    """
    print("\n  webpage2pdf repair")
    print("  " + "-" * 52)

    changed = False

    if sys.platform == "darwin" and not _dirs_containing_pango():
        import shutil
        if shutil.which("brew") is None:
            print("  Pango is missing and Homebrew is not installed.")
            print("  Install Homebrew first: https://brew.sh")
            return 1
        print("  Pango is missing. Installing it:")
        changed |= _run(["brew", "install", "pango"])

    missing = []
    for module in ("weasyprint", "bs4", "lxml", "requests", "PIL"):
        try:
            __import__(module)
        except Exception:
            missing.append(module)

    if missing:
        # Install the project, not the individual modules: the import names do
        # not all match their distribution names, and the pins live in
        # pyproject.toml anyway.
        print(f"  Missing Python packages: {', '.join(missing)}")
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        if os.path.isfile(os.path.join(project_root, "pyproject.toml")):
            changed |= _run(
                [sys.executable, "-m", "pip", "install", "-e", project_root])
        else:
            # No source checkout to reinstall from — this is a Homebrew or
            # packaged install with a broken venv. `pip install webpage2pdf`
            # is deliberately not attempted here: that name is already taken
            # on PyPI by an unrelated project (a different "webpage2pdf" by a
            # different author), so guessing would silently install the wrong
            # package instead of fixing this one. There is no supported plain
            # PyPI install of this project to fall back to.
            print("  No source checkout found to reinstall from.")
            print("  Reinstall using whichever method you installed with:")
            print("      brew reinstall webpage2pdf")
            print("  or, from a fresh checkout of the source:")
            print("      pip install -e /path/to/webpage2pdf")

    if not changed:
        print("  Nothing to repair.\n")
        return 0

    print("\n  Re-checking:")
    # The library path is worked out at process start, so a freshly installed
    # Pango is only visible to a new process.
    return _run([sys.executable, "-m", "webpage2pdf", "--doctor"]) and 0 or 1


def diagnose() -> int:
    """Print an environment report. Backs `webpage2pdf --doctor`."""
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
