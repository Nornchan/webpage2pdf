"""
profiles.py — named bundles of the settings that go together.

A preset is page geometry. A style is a stylesheet. A profile is the answer to
"what am I making?", and it fixes both plus the link handling, the numbering and
the output format — because those choices are not independent. Footnotes suit
paper and are pointless on screen. Section numbers help a reference document and
clutter an essay. A booklet wants mirrored margins and a contents list.

Users can add their own as TOML under ~/.config/webpage2pdf/profiles/. A user
profile with a built-in name replaces it.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, fields

from . import presets


@dataclass(frozen=True)
class Profile:
    name: str
    description: str

    fmt: str = "pdf"
    preset: str = presets.DEFAULT_PRESET
    style: str = "essay"
    links: str = "plain"
    numbered: bool = True
    toc: bool | None = None        # None = decide from the document
    images: bool = True
    show_url: bool = True
    standfirst: bool = True

    def settings(self) -> dict:
        """The convert() keyword arguments this profile implies."""
        data = asdict(self)
        data.pop("name")
        data.pop("description")
        return data


BUILTIN: dict[str, Profile] = {
    "essay": Profile(
        name="essay",
        description="A4, quiet links, contents list when the piece is long enough",
        fmt="pdf", preset="a4", links="plain",
    ),
    "reference": Profile(
        name="reference",
        description="Two columns, numbered sections, footnoted links — for material you search rather than read",
        fmt="pdf", preset="two-column", links="footnotes",
        numbered=True, toc=True,
    ),
    "booklet": Profile(
        name="booklet",
        description="6x9in facing pages with mirrored margins, footnotes, for printing double-sided and binding",
        fmt="pdf", preset="book", links="footnotes",
        numbered=False, toc=True,
    ),
    "device": Profile(
        name="device",
        description="Sized to a reMarkable screen, footnotes, no numbering",
        fmt="pdf", preset="remarkable", links="footnotes",
        numbered=False,
    ),
    "screen": Profile(
        name="screen",
        description="One self-contained HTML file, live links, fonts embedded",
        fmt="html", preset="a4", links="keep",
        numbered=False, toc=None,
    ),
    "ereader": Profile(
        name="ereader",
        description="Reflowable EPUB for a phone, Kobo or Kindle",
        fmt="epub", links="endnotes", numbered=False,
    ),
    "notes": Profile(
        name="notes",
        description="Markdown with front matter, for an archive or a notes folder",
        fmt="md", links="endnotes", numbered=False,
        standfirst=False,
    ),
}

DEFAULT_PROFILE = "essay"


def user_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "webpage2pdf", "profiles")


def _load_user() -> dict[str, Profile]:
    """
    Read ~/.config/webpage2pdf/profiles/*.toml.

    A malformed or unknown key is reported by name rather than ignored: a
    profile that silently does not do what it says is worse than one that
    refuses to load.
    """
    directory = user_dir()
    if not os.path.isdir(directory):
        return {}

    valid = {f.name for f in fields(Profile)}
    found: dict[str, Profile] = {}
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".toml"):
            continue
        path = os.path.join(directory, entry)
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"{path}: {exc}") from None

        name = data.pop("name", os.path.splitext(entry)[0])
        unknown = set(data) - valid
        if unknown:
            raise ValueError(
                f"{path}: unknown setting(s) {', '.join(sorted(unknown))}. "
                f"Valid: {', '.join(sorted(valid - {'name'}))}"
            )
        data.setdefault("description", f"user profile from {entry}")
        found[name] = Profile(name=name, **data)
    return found


def all_profiles() -> dict[str, Profile]:
    merged = dict(BUILTIN)
    merged.update(_load_user())     # a user profile of the same name wins
    return merged


def get(name: str) -> Profile:
    profiles = all_profiles()
    try:
        return profiles[name]
    except KeyError:
        raise ValueError(
            f"Unknown profile '{name}'. Available: " + ", ".join(sorted(profiles))
        ) from None


def names() -> list[str]:
    return sorted(all_profiles())
