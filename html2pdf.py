#!/usr/bin/env python3
"""
html2pdf.py — turn web pages into clean A4 PDFs.

    python3 html2pdf.py https://example.com/article
    python3 html2pdf.py saved-page.html -o reading/week-03.pdf
    python3 html2pdf.py url1 url2 file.html -d reading/
    python3 html2pdf.py --from-list links.txt -d reading/

Run `python3 html2pdf.py --help` for all options.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --doctor has to work even when the PDF engine can't load, so it is handled
# before `converter` (and therefore weasyprint) is imported.
if "--doctor" in sys.argv:
    import _bootstrap
    _bootstrap.ensure_native_libs()
    sys.exit(_bootstrap.diagnose())

import converter  # noqa: E402


GREEN, YELLOW, RED, DIM, BOLD, OFF = (
    ("\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
    if sys.stdout.isatty() else ("", "", "", "", "", "")
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="html2pdf",
        description="Convert web pages or saved HTML files into tidy A4 PDFs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  html2pdf.py https://aeon.co/essays/some-essay
  html2pdf.py article.html -o out/week-03.pdf
  html2pdf.py a.html b.html https://example.com/c -d reading/
  html2pdf.py --from-list weekly-links.txt -d reading/ --links endnotes
  html2pdf.py https://example.com/piece --no-numbering --no-images
""",
    )
    p.add_argument("sources", nargs="*",
                   help="URLs and/or paths to saved .html files")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="output PDF path (single source only)")
    p.add_argument("-d", "--dir", metavar="DIR", default=".",
                   help="output directory; filenames come from article titles")
    p.add_argument("--from-list", metavar="FILE",
                   help="read sources from a text file, one per line (# = comment)")
    p.add_argument("--style", default="essay",
                   help="stylesheet name from styles/ (default: essay)")
    p.add_argument("--links", choices=["plain", "endnotes", "keep"], default="plain",
                   help="plain: strip link styling; endnotes: numbered list at the "
                        "end; keep: live links (default: plain)")
    p.add_argument("--no-numbering", action="store_true",
                   help="omit automatic section and figure numbers")
    p.add_argument("--no-images", action="store_true",
                   help="text only — smaller files, faster")
    p.add_argument("--no-url", action="store_true",
                   help="omit the source URL from the title block")
    p.add_argument("--no-standfirst", action="store_true",
                   help="omit the italic summary line under the title")
    p.add_argument("--keep-html", metavar="FILE",
                   help="also save the cleaned HTML (useful for debugging)")
    p.add_argument("--timeout", type=int, default=30, metavar="SEC",
                   help="network timeout per request (default: 30)")
    p.add_argument("--list-styles", action="store_true",
                   help="show available stylesheets and exit")
    p.add_argument("--doctor", action="store_true",
                   help="check the installation and report what's wrong")
    p.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    return p


def gather_sources(args: argparse.Namespace) -> list[str]:
    sources = list(args.sources)
    if args.from_list:
        with open(args.from_list, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    sources.append(line)
    return sources


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_styles:
        for name in converter.available_styles():
            print(name)
        return 0

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
                out_path = os.path.join(args.dir, "__w2p_tmp__.pdf")

            result = converter.convert(
                source, out_path,
                style=args.style,
                numbered=not args.no_numbering,
                link_mode=args.links,
                show_url=not args.no_url,
                standfirst=not args.no_standfirst,
                images=not args.no_images,
                keep_html=args.keep_html,
                timeout=args.timeout,
            )

            if not args.output:
                final = os.path.join(args.dir, converter.suggest_filename(result.title))
                if os.path.abspath(final) != os.path.abspath(out_path):
                    if os.path.exists(final):
                        stem, ext = os.path.splitext(final)
                        n = 2
                        while os.path.exists(f"{stem}-{n}{ext}"):
                            n += 1
                        final = f"{stem}-{n}{ext}"
                    os.replace(out_path, final)
                result.pdf_path = os.path.abspath(final)

            if not args.quiet:
                size_kb = os.path.getsize(result.pdf_path) / 1024
                print(f"  {GREEN}✓{OFF} {BOLD}{result.pdf_path}{OFF}")
                print(f"    {DIM}{result.pages} pages · {result.word_count:,} words · "
                      f"{result.images} images · {size_kb:,.0f} KB{OFF}")
                for warning in result.warnings:
                    print(f"    {YELLOW}!{OFF} {warning}")

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Interrupted.{OFF}", file=sys.stderr)
            return 130
        except Exception as exc:
            failures += 1
            print(f"  {RED}✗ {type(exc).__name__}: {exc}{OFF}", file=sys.stderr)
            tmp = os.path.join(args.dir, "__w2p_tmp__.pdf")
            if os.path.exists(tmp):
                os.remove(tmp)

    if len(sources) > 1 and not args.quiet:
        ok = len(sources) - failures
        print(f"\n{BOLD}{ok}/{len(sources)} converted{OFF}"
              + (f" · {RED}{failures} failed{OFF}" if failures else ""))

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
