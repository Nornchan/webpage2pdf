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
    sys.exit(_bootstrap.diagnose())

from . import converter  # noqa: E402
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
                   help="URLs and/or paths to saved .html files")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="output PDF path (single source only)")
    p.add_argument("-d", "--dir", metavar="DIR", default=".",
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
    p.add_argument("--timeout", type=int, default=30, metavar="SEC",
                   help="network timeout per request (default: 30)")
    p.add_argument("--list-styles", action="store_true",
                   help="show available stylesheets and exit")
    p.add_argument("--list-presets", action="store_true",
                   help="show available page presets and exit")
    p.add_argument("--list-profiles", action="store_true",
                   help="show available profiles and exit")
    p.add_argument("--doctor", action="store_true",
                   help="check the installation and report what's wrong")
    p.add_argument("--open", dest="open_after", action="store_true",
                   help="open each finished PDF in the default viewer")
    p.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    return p


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
        with open(args.from_list, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    sources.append(line)
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
    profile = profiles.get(args.profile or profiles.DEFAULT_PROFILE)
    settings = profile.settings()

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

    failures = 0
    for index, source in enumerate(sources, start=1):
        label = source if len(source) <= 72 else source[:69] + "..."
        if not args.quiet:
            counter = f"[{index}/{len(sources)}] " if len(sources) > 1 else ""
            print(f"{DIM}{counter}{OFF}{label}")

        try:
            if args.output:
                out_path = args.output
            else:
                # Convert once to learn the title, then name the file after it.
                # The staging name carries the pid so two runs writing into the
                # same -d directory cannot overwrite each other's work.
                out_path = converter.staging_path(args.dir, fmt)

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
                timeout=args.timeout,
            )

            if not args.output:
                preferred = os.path.join(
                    args.dir, converter.suggest_filename(result.title, fmt=fmt)
                )
                final = converter.claim_output_path(preferred)
                converter.finalize_output(out_path, final)
                result.output_path = os.path.abspath(final)

            if not args.quiet:
                size_kb = os.path.getsize(result.output_path) / 1024
                print(f"  {GREEN}✓{OFF} {BOLD}{result.output_path}{OFF}")
                pages = f"{result.pages} pages · " if result.pages else ""
                print(f"    {DIM}{pages}{result.word_count:,} words · "
                      f"{result.images} images · {size_kb:,.0f} KB{OFF}")
                for warning in result.warnings:
                    print(f"    {YELLOW}!{OFF} {warning}")

            if args.open_after:
                _open_file(result.output_path)

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Interrupted.{OFF}", file=sys.stderr)
            return 130
        except Exception as exc:
            failures += 1
            print(f"  {RED}✗ {type(exc).__name__}: {exc}{OFF}", file=sys.stderr)
            tmp = converter.staging_path(args.dir, fmt)
            if os.path.exists(tmp):
                os.remove(tmp)

    if len(sources) > 1 and not args.quiet:
        ok = len(sources) - failures
        print(f"\n{BOLD}{ok}/{len(sources)} converted{OFF}"
              + (f" · {RED}{failures} failed{OFF}" if failures else ""))

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
