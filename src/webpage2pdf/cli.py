#!/usr/bin/env python3
"""
cli.py — turn web pages into clean A4 PDFs from the command line.

    webpage2pdf https://example.com/article
    webpage2pdf saved-page.html -o reading/week-03.pdf
    webpage2pdf url1 url2 file.html -d reading/
    webpage2pdf --from-list links.txt -d reading/

Run `webpage2pdf --help` for all options.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from . import __version__

# --doctor has to work even when the PDF engine cannot load — that is the whole
# point of it — so it is handled before `converter` (and therefore weasyprint)
# is imported. Same for --version, which should never depend on native libraries.
if "--doctor" in sys.argv:
    from . import _bootstrap
    _bootstrap.ensure_native_libs()
    if "--fix" in sys.argv:
        sys.exit(_bootstrap.repair())
    sys.exit(_bootstrap.diagnose())

from . import cache as cache_mod  # noqa: E402
from . import converter  # noqa: E402
from . import extractor  # noqa: E402
from . import presets  # noqa: E402
from . import profiles  # noqa: E402
from . import writers  # noqa: E402


GREEN, YELLOW, RED, DIM, BOLD, OFF = (
    ("\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
    if sys.stdout.isatty() else ("", "", "", "", "", "")
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webpage2pdf",
        description="Convert web pages or saved HTML files into tidy A4 PDFs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  webpage2pdf https://aeon.co/essays/some-essay
  webpage2pdf article.html -o out/week-03.pdf
  webpage2pdf a.html b.html https://example.com/c -d reading/
  webpage2pdf --from-list weekly-links.txt -d reading/ --links endnotes
  webpage2pdf https://example.com/piece --no-numbering --no-images

`w2p` is installed as a shorter alias for the same command.
""",
    )
    p.add_argument("-V", "--version", action="version",
                   version=f"webpage2pdf {__version__}")
    p.add_argument("sources", nargs="*",
                   help="URLs and/or paths to saved .html files; "
                        "- reads HTML from standard input")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="output path (single source only); - writes to stdout")
    p.add_argument("-d", "--dir", metavar="DIR", default=None,
                   help="output directory; filenames come from article titles")
    p.add_argument("--from-list", metavar="FILE",
                   help="read sources from a text file, one per line (# = comment)")
    try:
        known = ", ".join(profiles.names())
    except ValueError:
        # A broken user profile must not stop --help from working; the error is
        # reported properly by main() when the profile is actually resolved.
        known = ", ".join(sorted(profiles.BUILTIN))
    p.add_argument("-p", "--profile", default=None, metavar="NAME",
                   help="named bundle of settings: " + known
                        + f" (default: {profiles.DEFAULT_PROFILE}). Any other "
                          "flag you give overrides it.")
    p.add_argument("-f", "--format", dest="fmt", default=None,
                   choices=list(writers.FORMATS), metavar="FMT",
                   help="output format: " + ", ".join(writers.FORMATS)
                        + " (default: inferred from -o, else pdf)")
    p.add_argument("--preset", default=None, metavar="NAME",
                   help="page geometry: " + ", ".join(presets.names())
                        + f" (default: {presets.DEFAULT_PRESET})")
    p.add_argument("--style", default=None,
                   help="stylesheet name from styles/ (default: essay)")
    p.add_argument("--links", choices=["plain", "endnotes", "footnotes", "keep"],
                   default=None,
                   help="plain: strip link styling; endnotes: numbered list at the "
                        "end; footnotes: URL at the foot of the page it appears "
                        "on; keep: live links (default: plain)")
    toc_group = p.add_mutually_exclusive_group()
    toc_group.add_argument("--toc", dest="toc", action="store_true", default=None,
                           help="add a contents list with page numbers")
    toc_group.add_argument("--no-toc", dest="toc", action="store_false",
                           help="never add a contents list")
    p.add_argument("--no-numbering", action="store_true", default=None,
                   help="omit automatic section and figure numbers")
    p.add_argument("--no-images", action="store_true", default=None,
                   help="text only — smaller files, faster")
    p.add_argument("--no-url", action="store_true", default=None,
                   help="omit the source URL from the title block")
    p.add_argument("--no-standfirst", action="store_true", default=None,
                   help="omit the italic summary line under the title")
    p.add_argument("--keep-html", metavar="FILE",
                   help="also save the cleaned HTML (useful for debugging)")
    p.add_argument("-j", "--jobs", type=int, default=None, metavar="N",
                   help="fetch this many pages at once when converting a batch "
                        "(default: 4; rendering stays single-threaded)")
    p.add_argument("--no-cache", action="store_true",
                   help="do not read or write the fetch cache")
    p.add_argument("--refresh", action="store_true",
                   help="re-fetch even when a cached copy is held")
    p.add_argument("--cache-info", action="store_true",
                   help="show what the cache holds and exit")
    p.add_argument("--clear-cache", action="store_true",
                   help="delete everything in the cache and exit")
    p.add_argument("--timeout", type=int, default=None, metavar="SEC",
                   help="network timeout per request (default: 30)")
    p.add_argument("--cookies", metavar="FILE", default=None,
                   help="send cookies from FILE (cookies.txt, a JSON cookie "
                        "export, or a pasted Cookie: header line) so a page "
                        "you can only read signed in converts too")
    p.add_argument("--list-styles", action="store_true",
                   help="show available stylesheets and exit")
    p.add_argument("--list-presets", action="store_true",
                   help="show available page presets and exit")
    p.add_argument("--list-profiles", action="store_true",
                   help="show available profiles and exit")
    p.add_argument("--doctor", action="store_true",
                   help="check the installation and report what's wrong")
    p.add_argument("--fix", action="store_true",
                   help="with --doctor, attempt the repairs it recommends")
    p.add_argument("--open", dest="open_after", action="store_true", default=None,
                   help="open each finished PDF in the default viewer")
    p.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    return p


def prefetch(sources: list[str], store, timeout: int, jobs: int,
             report, cookies=None) -> None:
    """
    Warm the cache for every URL at once, before rendering any of them.

    Only the fetching is parallel. WeasyPrint offers no thread-safety guarantee
    and drives Pango and cairo through cffi with shared fontconfig state, so
    rendering stays on one thread; the network, which is the part that actually
    takes the time, does not have to. The serial render loop afterwards finds
    everything already cached.
    """
    urls = [s for s in sources if s.startswith(("http://", "https://"))]
    if len(urls) < 2 or jobs < 2 or not store.enabled:
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def warm(url: str) -> tuple[str, bool]:
        try:
            extractor.fetch(url, timeout=timeout, store=store, cookies=cookies)
            return url, True
        except Exception:
            # A failure here is not fatal: the render loop will retry the fetch
            # and report the error properly, with its own context.
            return url, False

    done = 0
    with ThreadPoolExecutor(max_workers=min(jobs, len(urls))) as pool:
        futures = [pool.submit(warm, u) for u in urls]
        for future in as_completed(futures):
            done += 1
            report(done, len(urls))


def _open_file(path: str) -> None:
    """
    Show the finished PDF in the platform's default viewer.

    Best effort throughout: failing to open a viewer is never a reason to
    report a conversion that already succeeded as failed.
    """
    if sys.platform == "darwin":
        opener = ["open"]
    elif sys.platform.startswith("win"):
        opener = ["cmd", "/c", "start", ""]
    elif shutil.which("xdg-open"):
        opener = ["xdg-open"]
    else:
        return
    try:
        subprocess.run([*opener, path], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def gather_sources(args: argparse.Namespace) -> list[str]:
    sources = list(args.sources)
    if args.from_list:
        stream = sys.stdin if args.from_list == "-" else open(
            args.from_list, encoding="utf-8")
        try:
            for line in stream:
                line = line.strip()
                if line and not line.startswith("#"):
                    sources.append(line)
        finally:
            if stream is not sys.stdin:
                stream.close()
    return sources


def resolve_settings(args: argparse.Namespace) -> dict:
    """
    Work out the settings for this run.

    Three layers, each overriding the one before:

        1. the profile — a named bundle, `essay` unless --profile says otherwise
        2. the output filename — `-o notes.md` plainly means Markdown
        3. any flag actually given on the command line

    Telling layer 3 from "left at its default" is why the flags default to None
    rather than to their real defaults. Without that, --profile notes could not
    select Markdown, because --format would always look like it had been given.
    """
    config = profiles.load_config()

    profile = profiles.get(
        args.profile or config.get("profile") or profiles.DEFAULT_PROFILE)
    settings = profile.settings()

    # Settings that are not part of a profile, but that you would otherwise
    # retype on every run.
    settings["dir"] = args.dir if args.dir is not None else config.get("dir", ".")
    settings["jobs"] = args.jobs if args.jobs is not None else int(config.get("jobs", 4))
    settings["timeout"] = (args.timeout if args.timeout is not None
                           else int(config.get("timeout", 30)))
    settings["open_after"] = (args.open_after if args.open_after is not None
                              else bool(config.get("open", False)))
    settings["cookies"] = (args.cookies if args.cookies is not None
                           else config.get("cookies") or None)
    if not config.get("cache", True):
        settings["no_cache"] = True

    # An output filename is a weaker signal than a flag but a stronger one than
    # a profile default: someone writing -o piece.epub means it.
    if args.fmt is None and args.output:
        suffix = os.path.splitext(args.output)[1].lstrip(".").lower()
        if suffix in writers.FORMATS:
            settings["fmt"] = suffix

    explicit = {
        "fmt": args.fmt,
        "preset": args.preset,
        "style": args.style,
        "links": args.links,
        "toc": args.toc,
        "numbered": None if args.no_numbering is None else False,
        "images": None if args.no_images is None else False,
        "show_url": None if args.no_url is None else False,
        "standfirst": None if args.no_standfirst is None else False,
    }
    for key, value in explicit.items():
        if value is not None:
            settings[key] = value

    presets.get(settings["preset"])          # raises on an unknown name
    if settings["fmt"] not in writers.FORMATS:
        raise ValueError(f"Unknown format '{settings['fmt']}'. "
                         f"Available: {', '.join(writers.FORMATS)}")
    return settings


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cache_info:
        info = cache_mod.Cache().stats()
        print(f"{info['directory']}\n"
              f"  {info['pages']} pages, {info['assets']} images, "
              f"{info['bytes'] / 1024 / 1024:.1f} MB")
        return 0

    if args.clear_cache:
        store = cache_mod.Cache()
        before = store.stats()
        store.clear()
        print(f"Cleared {before['pages']} pages and {before['assets']} images "
              f"({before['bytes'] / 1024 / 1024:.1f} MB) from {before['directory']}")
        return 0

    if args.list_styles:
        for name in converter.available_styles():
            print(name)
        return 0

    if args.list_presets:
        for name in presets.names():
            page = presets.get(name)
            print(f"{name:<12} {page.page_width_mm:g}x{page.page_height_mm:g}mm"
                  f"  {page.description}")
        return 0

    if args.list_profiles:
        try:
            for name in profiles.names():
                profile = profiles.get(name)
                print(f"{name:<11} {profile.fmt:<5} {profile.preset:<11} "
                      f"{profile.description}")
        except ValueError as exc:
            print(f"{RED}{exc}{OFF}", file=sys.stderr)
            return 1
        return 0

    try:
        settings = resolve_settings(args)
    except ValueError as exc:
        print(f"{RED}{exc}{OFF}", file=sys.stderr)
        return 1
    fmt = settings["fmt"]

    sources = gather_sources(args)
    if not sources:
        build_parser().print_help()
        return 1

    if args.output and len(sources) > 1:
        print(f"{RED}--output takes a single source; use --dir for batches.{OFF}",
              file=sys.stderr)
        return 1

    # Resolved once, here: a typo in the path should stop the run before the
    # first request, not once per source in the middle of a batch.
    cookies = settings.get("cookies")
    if cookies:
        try:
            cookies = extractor.load_cookies(cookies)
        except (OSError, ValueError) as exc:
            print(f"{RED}{exc}{OFF}", file=sys.stderr)
            return 1

    store = cache_mod.Cache(
        enabled=not (args.no_cache or settings.get("no_cache")),
        refresh=args.refresh)

    def report(done: int, total: int) -> None:
        if args.quiet or not sys.stderr.isatty():
            return
        print(f"\r{DIM}  fetching {done}/{total}…{OFF}", end="", file=sys.stderr)
        if done == total:
            print("\r" + " " * 28 + "\r", end="", file=sys.stderr)

    prefetch(sources, store, settings["timeout"], settings["jobs"], report,
             cookies=cookies)

    # `-` as a source means HTML on standard input. Stage it as a file, since
    # the converter works from paths and the extractor needs a base URL to
    # resolve relative links against — there isn't one for a pipe.
    stdin_staged = None
    if "-" in sources:
        import tempfile as _tempfile
        data = sys.stdin.read()
        fd, stdin_staged = _tempfile.mkstemp(suffix=".html", prefix="w2p-stdin-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        sources = [stdin_staged if s == "-" else s for s in sources]

    # `-o -` writes the finished file to standard output, so the tool composes
    # with a pipeline. Progress chatter goes to stderr in that case, or it would
    # corrupt the document.
    to_stdout = args.output == "-"
    if to_stdout:
        import tempfile as _tempfile
        args.output = os.path.join(
            _tempfile.mkdtemp(prefix="w2p-out-"), f"out.{fmt}")

    failures = 0
    for index, source in enumerate(sources, start=1):
        label = source if len(source) <= 72 else source[:69] + "..."
        if not args.quiet and not to_stdout:
            counter = f"[{index}/{len(sources)}] " if len(sources) > 1 else ""
            print(f"{DIM}{counter}{OFF}{label}")

        try:
            if args.output:
                out_path = args.output
            else:
                # Convert once to learn the title, then name the file after it.
                # The staging name carries the pid so two runs writing into the
                # same -d directory cannot overwrite each other's work.
                out_path = converter.staging_path(settings["dir"], fmt)

            def on_phase(label: str, _src=label) -> None:
                if args.quiet or to_stdout or not sys.stderr.isatty():
                    return
                print(f"\r{DIM}    {label}…{OFF}\033[K", end="", file=sys.stderr)

            result = converter.convert(
                source, out_path,
                style=settings["style"],
                numbered=settings["numbered"],
                link_mode=settings["links"],
                show_url=settings["show_url"],
                standfirst=settings["standfirst"],
                images=settings["images"],
                toc=settings["toc"],
                preset=settings["preset"],
                fmt=fmt,
                keep_html=args.keep_html,
                timeout=settings["timeout"],
                store=store,
                cookies=cookies,
                on_phase=on_phase,
            )

            if not args.output:
                preferred = os.path.join(
                    settings["dir"], converter.suggest_filename(result.title, fmt=fmt)
                )
                final = converter.claim_output_path(preferred)
                converter.finalize_output(out_path, final)
                result.output_path = os.path.abspath(final)

            if not args.quiet and not to_stdout and sys.stderr.isatty():
                print("\r\033[K", end="", file=sys.stderr)

            if to_stdout:
                with open(result.output_path, "rb") as fh:
                    sys.stdout.buffer.write(fh.read())
                sys.stdout.buffer.flush()

            if not args.quiet and not to_stdout:
                size_kb = os.path.getsize(result.output_path) / 1024
                print(f"  {GREEN}✓{OFF} {BOLD}{result.output_path}{OFF}")
                pages = f"{result.pages} pages · " if result.pages else ""
                print(f"    {DIM}{pages}{result.word_count:,} words · "
                      f"{result.images} images · {size_kb:,.0f} KB{OFF}")
                for warning in result.warnings:
                    print(f"    {YELLOW}!{OFF} {warning}")

            if settings["open_after"]:
                _open_file(result.output_path)

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Interrupted.{OFF}", file=sys.stderr)
            return 130
        except extractor.FetchBlocked as exc:
            # This one arrives already written for a person: a bare
            # "HTTPError: 403 Client Error" tells you nothing you can act on,
            # and acting on it is the whole point.
            failures += 1
            if not args.quiet and not to_stdout and sys.stderr.isatty():
                print("\r\033[K", end="", file=sys.stderr)
            lines = str(exc).split("\n")
            print(f"  {RED}✗ {lines[0]}{OFF}", file=sys.stderr)
            for line in lines[1:]:
                print(f"    {line}" if line else "", file=sys.stderr)
        except Exception as exc:
            failures += 1
            print(f"  {RED}✗ {type(exc).__name__}: {exc}{OFF}", file=sys.stderr)
            tmp = converter.staging_path(settings["dir"], fmt)
            if os.path.exists(tmp):
                os.remove(tmp)

    if stdin_staged and os.path.exists(stdin_staged):
        os.remove(stdin_staged)

    if len(sources) > 1 and not args.quiet and not to_stdout:
        ok = len(sources) - failures
        print(f"\n{BOLD}{ok}/{len(sources)} converted{OFF}"
              + (f" · {RED}{failures} failed{OFF}" if failures else ""))

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
