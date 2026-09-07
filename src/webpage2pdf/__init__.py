"""
webpage2pdf — turn web pages into clean A4 PDFs that read like typeset essays.

The package is deliberately layered:

    extractor   parse HTML, find the article, clean and rebuild it
    converter   assemble a cleaned Article into a PDF (the only WeasyPrint user)
    cli         command-line front end
    server      local drag-and-drop web front end
    _bootstrap  macOS native-library path fix, imported before WeasyPrint

Nothing outside `converter` should need to know a PDF engine exists.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
