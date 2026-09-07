"""
presets.py — page geometry, in one place.

Geometry used to live in two places that had to be kept in step by hand: the
@page rule in essay.css, and TEXT_WIDTH_MM / TEXT_HEIGHT_MM in converter.py,
which is what images are fitted against. Change one and forget the other and
images either overflow the page or are shrunk for no reason. The README's
advice on doing so was actively wrong.

Here a preset is the single source. It emits the CSS *and* reports the text
block, so the two cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    """One page geometry. Millimetres throughout; this is a paper document."""

    name: str
    description: str

    page_width_mm: float
    page_height_mm: float

    margin_top_mm: float
    margin_bottom_mm: float
    margin_inner_mm: float      # left on a recto, right on a verso when facing
    margin_outer_mm: float

    body_pt: float = 11.0
    line_height: float = 1.62
    columns: int = 1
    column_gap_mm: float = 7.0

    # True mirrors the inner/outer margins across facing pages, which is what
    # you want for anything destined to be bound or printed double-sided.
    facing: bool = False

    # Headroom kept below the maximum image height so a full-height image and
    # its caption still fit inside one unbreakable figure. See converter.
    caption_headroom_mm: float = 55.0

    # ---- derived ---------------------------------------------------------

    @property
    def measure_mm(self) -> float:
        """Width of the text block."""
        return self.page_width_mm - self.margin_inner_mm - self.margin_outer_mm

    @property
    def text_width_mm(self) -> float:
        """Width an image may occupy — one column, not the whole measure."""
        if self.columns > 1:
            total_gap = self.column_gap_mm * (self.columns - 1)
            return (self.measure_mm - total_gap) / self.columns
        return self.measure_mm

    @property
    def text_height_mm(self) -> float:
        """Height an image may occupy, with room left for its caption."""
        block = self.page_height_mm - self.margin_top_mm - self.margin_bottom_mm
        return max(block - self.caption_headroom_mm, block * 0.5)

    # ---- CSS -------------------------------------------------------------

    def css(self) -> str:
        """
        An override stylesheet, applied after essay.css.

        Only geometry is set here. Everything else — typography, page-break
        rules, the running heads — stays in the stylesheet, so a preset works
        with any --style.
        """
        rules = [
            f"/* preset: {self.name} — {self.description} */",
            "@page {",
            f"    size: {self.page_width_mm}mm {self.page_height_mm}mm;",
        ]

        if self.facing:
            # Symmetric margins by default, then mirrored per side below.
            rules.append(
                f"    margin: {self.margin_top_mm}mm {self.margin_outer_mm}mm "
                f"{self.margin_bottom_mm}mm {self.margin_inner_mm}mm;"
            )
            rules.append("}")
            rules += [
                "/* Bound or printed double-sided: the inner margin is the one",
                "   the binding eats, so it sits on the right of a verso and the",
                "   left of a recto. */",
                "@page :left {",
                f"    margin-left: {self.margin_outer_mm}mm;",
                f"    margin-right: {self.margin_inner_mm}mm;",
                "}",
                "@page :right {",
                f"    margin-left: {self.margin_inner_mm}mm;",
                f"    margin-right: {self.margin_outer_mm}mm;",
                "}",
            ]
        else:
            rules.append(
                f"    margin: {self.margin_top_mm}mm {self.margin_outer_mm}mm "
                f"{self.margin_bottom_mm}mm {self.margin_inner_mm}mm;"
            )
            rules.append("}")

        rules += [
            "html {",
            f"    font-size: {self.body_pt}pt;",
            f"    line-height: {self.line_height};",
            "}",
        ]

        if self.columns > 1:
            rules += [
                "main {",
                f"    column-count: {self.columns};",
                f"    column-gap: {self.column_gap_mm}mm;",
                "}",
                "/* A figure wider than its column would overflow, so figures and",
                "   tables span the full measure instead. */",
                "figure, .w2p-toc { column-span: all; }",
            ]

        # Images are fitted in Python against text_height_mm; this is the
        # backstop if that calculation is ever bypassed.
        rules += [
            "figure img {",
            f"    max-height: {self.text_height_mm:.1f}mm;",
            "}",
        ]
        return "\n".join(rules)


PRESETS: dict[str, Preset] = {
    "a4": Preset(
        name="a4",
        description="A4 portrait, 25mm margins — the default",
        page_width_mm=210, page_height_mm=297,
        margin_top_mm=25, margin_bottom_mm=22,
        margin_inner_mm=25, margin_outer_mm=25,
    ),
    "letter": Preset(
        name="letter",
        description="US Letter, 1in margins",
        page_width_mm=215.9, page_height_mm=279.4,
        margin_top_mm=25.4, margin_bottom_mm=22.4,
        margin_inner_mm=25.4, margin_outer_mm=25.4,
    ),
    "a5": Preset(
        name="a5",
        description="A5 — half of A4, comfortable in one hand",
        page_width_mm=148, page_height_mm=210,
        margin_top_mm=15, margin_bottom_mm=14,
        margin_inner_mm=15, margin_outer_mm=15,
        body_pt=10.0, line_height=1.55,
        caption_headroom_mm=38,
    ),
    "book": Preset(
        name="book",
        description="6x9in trim, facing pages with mirrored margins, for binding",
        page_width_mm=152.4, page_height_mm=228.6,
        margin_top_mm=18, margin_bottom_mm=18,
        margin_inner_mm=22, margin_outer_mm=16,
        body_pt=10.2, line_height=1.58,
        facing=True,
        caption_headroom_mm=42,
    ),
    "remarkable": Preset(
        name="remarkable",
        description="reMarkable 2 e-ink screen, narrow margins to use the glass",
        page_width_mm=157, page_height_mm=210,
        margin_top_mm=12, margin_bottom_mm=12,
        margin_inner_mm=12, margin_outer_mm=12,
        body_pt=10.5, line_height=1.6,
        caption_headroom_mm=38,
    ),
    "two-column": Preset(
        name="two-column",
        description="A4 in two columns, for dense reference material",
        page_width_mm=210, page_height_mm=297,
        margin_top_mm=20, margin_bottom_mm=18,
        margin_inner_mm=18, margin_outer_mm=18,
        body_pt=9.5, line_height=1.45,
        columns=2, column_gap_mm=7,
        caption_headroom_mm=45,
    ),
}

DEFAULT_PRESET = "a4"


def get(name: str) -> Preset:
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(
            f"Unknown preset '{name}'. Available: " + ", ".join(sorted(PRESETS))
        ) from None


def names() -> list[str]:
    return sorted(PRESETS)
