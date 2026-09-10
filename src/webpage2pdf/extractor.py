"""
extractor.py — turn a messy web page into clean, semantic HTML.

The job here is structural, not cosmetic. We work out which part of the page is
actually the article, throw away the furniture (nav, share buttons, related-story
rails, newsletter nags), and then rebuild what's left as a small, predictable set
of tags: h1-h4, p, ul/ol, blockquote, figure/figcaption, table, pre.

Everything downstream (the stylesheet, the page-break rules) can then assume a
tidy document instead of guessing at whatever div soup the site shipped.
"""

from __future__ import annotations

import base64
import hashlib
import io
import mimetypes
import os
import re
import urllib.parse
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# Elements that never survive, wherever they appear.
DROP_TAGS = {
    "script", "style", "noscript", "iframe", "form", "button", "input",
    "select", "textarea", "object", "embed", "canvas", "template",
    "link", "meta", "svg", "video", "audio", "source", "track", "map",
    "ins", "dialog",
}

# Whole-page furniture: removed before we choose the article container.
STRUCTURAL_JUNK = re.compile(
    r"(^|[-_\s])("
    r"nav|navigation|navbar|navbox|menu|megamenu|topbar|sidebar|side-bar|"
    r"footer|masthead|banner|breadcrumb|pagination|paginate|"
    r"skip-link|screen-reader|sr-only|visually-hidden|noprint|"
    r"cookie|consent|gdpr|privacy-banner|"
    r"modal|popup|overlay|lightbox|drawer|offcanvas|"
    # Encyclopaedia and CMS chrome that otherwise reads as body text
    r"toc|table-of-contents|tableofcontents|toctitle|toc-container|"
    r"infobox|vcard|metadata|catlinks|printfooter|sitesub|site-sub|"
    r"hatnote|shortdescription|ambox|mbox|sistersitebox|mw-jump|"
    r"editsection|edit-section|headerlink|header-link|anchor-link|permalink"
    r")([-_\s]|$)",
    re.I,
)

# Elements the page itself marks as hidden when printing. Our whole job is to
# render for print, so an explicit "not when printing" directive from the site
# is the most reliable furniture signal there is — publishers hang it on the
# duplicated responsive copies of a hero image, on share bars, and on the
# "more from this site" rails below the article. Tailwind writes it
# `print:hidden`; Bootstrap and hand-rolled stylesheets use the rest.
PRINT_HIDDEN = re.compile(
    r"(^|\s)("
    r"print:hidden|print:none|print:sr-only|"
    r"d-print-none|hidden-print|hidden--print|no-print|noprint|is-print-hidden|"
    r"u-hidden-print|visually-hidden-print|screen-only|screenreader-print"
    r")(\s|$)",
    re.I,
)

# Anchors that are page furniture rather than prose: "edit", "¶", "jump to".
JUNK_ANCHOR_TEXT = re.compile(
    r"^\s*(edit|edit source|\[edit\]|¶|#|§|link|permalink|jump to[\w\s]*|"
    r"enlarge|expand|collapse|show|hide|top|back to top)\s*$", re.I
)

# Classes that mark a caption sitting outside its <figure>.
CAPTION_HINT = re.compile(
    r"(^|[-_\s])(thumbcaption|wp-caption-text|caption|image-caption|media-caption|"
    r"figure-caption|figcaption|photo-caption|credit-caption)([-_\s]|$)", re.I
)

# In-article clutter: removed after the container is chosen, so we don't
# accidentally eat the headline or a legitimate section.
INLINE_JUNK = re.compile(
    r"(^|[-_\s])("
    r"share|sharing|social|socials|follow-us|"
    r"advert|advertis|adsbygoogle|ad-slot|ad-unit|ad-container|google-ad|dfp|"
    r"promo|promotion|sponsor|sponsored|partner-content|taboola|outbrain|"
    r"subscribe|subscription|newsletter|signup|sign-up|paywall|piano|meter|"
    r"comment|comments|disqus|livefyre|"
    r"related|recommend|recirc|read-next|read-more|more-from|more-on|"
    r"trending|popular|most-read|latest-news|"
    r"author-bio|contributor-bio|newsletter-form|"
    r"toolbar|utility-bar|action-bar|toolbelt|"
    r"caption-credit-only|image-credit-standalone"
    r")([-_\s]|$)",
    re.I,
)

# URL fragments that mark an image as decoration or telemetry rather than content.
JUNK_IMAGE_URL = re.compile(
    r"(spacer|pixel|blank|1x1|transparent|tracking|beacon|analytics|"
    r"logo|icon|avatar|sprite|badge|button|arrow|bullet|divider|"
    r"placeholder|loading|spinner|lazy-?load|data:image/gif;base64,R0lGOD)",
    re.I,
)

INLINE_TAGS = {
    "a", "b", "strong", "i", "em", "u", "span", "code", "sub", "sup",
    "abbr", "cite", "q", "small", "mark", "time", "br", "s", "del", "ins",
    "kbd", "samp", "var", "big", "font", "tt", "label", "bdi", "bdo", "wbr",
}

BLOCK_TAGS = {
    "p", "div", "section", "article", "aside", "h1", "h2", "h3", "h4", "h5",
    "h6", "ul", "ol", "li", "blockquote", "pre", "table", "figure", "hr",
    "dl", "dt", "dd", "header", "footer", "main", "nav", "details",
}

# Attributes we keep. Everything else is stripped so no site CSS leaks through.
KEEP_ATTRS = {
    # `style` survives on <img> only: it carries the computed print width that
    # keeps tall images inside a single page.
    "img": {"src", "alt", "style"},
    "a": {"href"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    "ol": {"start", "type", "class"},
    "ul": {"class"},
    "figure": {"class"},
    "div": {"class"},
    "span": {"class"},
    "p": {"class"},
}


@dataclass
class Article:
    """The finished, cleaned document, ready to be poured into a template."""

    title: str = ""
    byline: str = ""
    published: str = ""
    site: str = ""
    lang: str = "en"   # BCP-47; drives WeasyPrint's hyphenation dictionary
    source_url: str = ""
    excerpt: str = ""
    body_html: str = ""
    word_count: int = 0
    images: int = 0
    endnotes: list[tuple[str, str]] = field(default_factory=list)
    sections: list[tuple[int, str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

# A bare User-Agent is not what a browser sends. Sites that turn away thin
# requests generally look at the whole set — the fetch metadata headers, the
# hint that this is a top-level navigation — so we send the set, not one line
# of it. This is not a disguise: the request is still a plain GET from a
# script, and the walls below see through it. It just stops well-behaved
# origins from mistaking a normal request for a scraper.
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# Commercial bot walls, recognised from what they serve with the refusal.
# Naming the wall matters because it tells the user what kind of problem they
# have: none of these can be talked round with headers — they want a browser
# that runs their JavaScript challenge — so the fix is always to bring the
# page (or the session) from a browser rather than to retry differently.
BOT_WALLS = (
    (re.compile(r"captcha-delivery\.com|datadome", re.I), "DataDome"),
    (re.compile(r"cf-browser-verification|cf_chl_|__cf_chl|"
                r"Attention Required!.{0,40}Cloudflare", re.I | re.S), "Cloudflare"),
    (re.compile(r"_px[A-Za-z]*Captcha|perimeterx|px-captcha", re.I), "PerimeterX"),
    (re.compile(r"Reference #[0-9a-f.]{8,}|akamai", re.I), "Akamai"),
    (re.compile(r"incapsula|_Incapsula_Resource", re.I), "Imperva"),
)


class FetchBlocked(RuntimeError):
    """
    The server answered, and the answer was no.

    Kept apart from requests' HTTPError because it is not the same kind of
    event: nothing is broken, and no retry of the same shape will help. The
    message carries the way out.
    """

    def __init__(self, url: str, status: int, wall: str | None = None,
                 detail: str = ""):
        self.url = url
        self.status = status
        self.wall = wall
        super().__init__(describe_block(url, status, wall, detail))


def describe_wall(body: str) -> str | None:
    """Name the bot wall behind a refusal, if it left a recognisable trace."""
    for pattern, name in BOT_WALLS:
        if pattern.search(body):
            return name
    return None


def _wrap(text: str, width: int = 74) -> str:
    """Fold a sentence to terminal width; the caller indents what it gets."""
    import textwrap
    return "\n".join(textwrap.wrap(text, width)) or text


def describe_block(url: str, status: int, wall: str | None = None,
                   detail: str = "") -> str:
    """The human half of a refusal: what happened, and what to do instead."""
    host = urllib.parse.urlparse(url).netloc or url
    reason = {
        401: "asked for a login",
        403: "refused the request",
        429: "is rate-limiting this address",
        451: "blocked the request for legal reasons",
    }.get(status, "refused the request")

    lines = [f"{host} {reason} (HTTP {status}"
             + (f", {wall} bot protection" if wall else "") + ")."]

    if status == 429:
        lines += [
            "",
            _wrap("Too many requests too quickly. Wait a few minutes, and use "
                  "-j 1 for large batches from one site."),
        ]
        return "\n".join(lines)

    if wall:
        lines += [
            "",
            _wrap(f"{wall} wants a browser that runs its JavaScript challenge, "
                  "so no header this tool can send will get past it. The page "
                  "itself is fine — only this request was turned away."),
        ]
    elif status == 401:
        lines += ["", "The page is behind a login."]

    lines += [
        "",
        "Two ways through, both from a browser where the page opens normally:",
        "",
        "  1. Save it — File > Save Page As > \"Web Page, Complete\" —",
        "     and convert the file:",
        "         w2p ~/Downloads/page.html",
        "",
        "  2. Or hand over your own session, if you have access to the page:",
        "         w2p --cookies cookies.txt " + url,
        "     (export cookies.txt for the site with a cookies.txt browser "
        "extension)",
    ]
    if detail:
        lines += ["", _wrap(detail)]
    return "\n".join(lines)


def load_cookies(source: str) -> "requests.cookies.RequestsCookieJar":
    """
    Read cookies from a file, so a request can carry the session you already
    have in your browser.

    Three shapes are accepted, because that is what the exporters produce:
    Netscape cookies.txt (curl, wget, most browser extensions), the JSON array
    the rest of the extensions produce, and a single `name=value; name=value`
    header line pasted out of a browser's network tab.
    """
    path = os.path.abspath(os.path.expanduser(source))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No such cookie file: {path}")

    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read().strip()

    jar = requests.cookies.RequestsCookieJar()

    if text.startswith(("[", "{")):
        import json
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ValueError(f"{path}: not valid JSON ({exc})") from exc
        items = data if isinstance(data, list) else data.get("cookies", [])
        for item in items:
            if not isinstance(item, dict) or "name" not in item:
                continue
            jar.set(item["name"], item.get("value", ""),
                    domain=(item.get("domain") or "").lstrip("."),
                    path=item.get("path") or "/")
        if not len(jar):
            raise ValueError(f"{path}: JSON held no cookies")
        return jar

    if "\n" not in text and "=" in text and "\t" not in text:
        # A pasted Cookie: header line. It carries no domain, so it is sent to
        # whatever host is being fetched — which is what pasting it means.
        for part in text.replace("Cookie:", "", 1).split(";"):
            name, _, value = part.strip().partition("=")
            if name:
                jar.set(name, value)
        if not len(jar):
            raise ValueError(f"{path}: no cookies found on that line")
        return jar

    import http.cookiejar
    mozilla = http.cookiejar.MozillaCookieJar()
    try:
        mozilla.load(path, ignore_discard=True, ignore_expires=True)
    except (http.cookiejar.LoadError, OSError) as exc:
        raise ValueError(
            f"{path}: not a cookies.txt file, a JSON cookie export, or a "
            f"Cookie: header line ({exc})"
        ) from exc
    for cookie in mozilla:
        # A session cookie is written with an expiry of 0, and the ones that
        # matter here — the sign-in, the bot wall's pass — usually are one.
        # Loading ignores expiry; *sending* does not, and would drop every one
        # of them as expired half a century ago.
        if not cookie.expires:
            cookie.expires = None
        jar.set_cookie(cookie)
    if not len(jar):
        raise ValueError(f"{path}: the cookie file is empty")
    return jar


def _as_jar(cookies):
    """Accept a path or an already-built jar, since callers have both."""
    if cookies is None or isinstance(cookies, str):
        return load_cookies(cookies) if cookies else None
    return cookies


def fetch(url: str, timeout: int = 30, store=None, cookies=None) -> tuple[str, str]:
    """
    Download a page. Returns (html, final_url) after redirects.

    `store` is an optional cache.Cache. Converting one article to a second
    format, or trying it against another profile, should not re-download it.
    `cookies` is a path to a cookie file or a jar from load_cookies(), which
    lets a request carry the session you already have in a browser.

    Raises FetchBlocked — with the way out in its message — when the server
    turns the request away rather than failing.
    """
    if store is not None:
        hit = store.get_page(url)
        if hit is not None:
            return hit

    jar = _as_jar(cookies)
    session = requests.Session()
    if jar is not None:
        session.cookies.update(jar)

    headers = dict(BROWSER_HEADERS)
    resp = session.get(url, headers=headers, timeout=timeout)

    # A plain 403 with nothing behind it is often hotlink protection, which
    # wants to see that the request came from the site's own pages. That is
    # one cheap retry, and it is the only one worth making: a wall that named
    # itself has already told us no retry will do.
    if resp.status_code == 403 and describe_wall(resp.text[:20000]) is None:
        root = "{0.scheme}://{0.netloc}/".format(urllib.parse.urlparse(url))
        retry_headers = dict(headers,
                             Referer=root, **{"Sec-Fetch-Site": "same-origin"})
        retry = session.get(url, headers=retry_headers, timeout=timeout)
        if retry.ok:
            resp = retry

    if resp.status_code in (401, 403, 429, 451):
        wall = describe_wall(resp.text[:20000])
        detail = ""
        if jar is not None:
            detail = ("The cookies you supplied were sent and did not satisfy "
                      "it — they may be stale, or for a different host.")
        raise FetchBlocked(url, resp.status_code, wall, detail)

    resp.raise_for_status()

    # requests' default latin-1 guess for text/* mangles UTF-8 pages, so only
    # trust the declared charset when the server actually declared one.
    if resp.encoding and "charset" not in resp.headers.get("content-type", "").lower():
        resp.encoding = resp.apparent_encoding or resp.encoding

    if store is not None:
        store.put_page(url, resp.text, resp.url)
    return resp.text, resp.url


def read_local(path: str) -> tuple[str, str]:
    """Read a saved .html file. Returns (html, file:// base URL)."""
    with open(path, "rb") as fh:
        raw = fh.read()

    html = None
    # Honour a declared charset if there is one, otherwise try the usual suspects.
    match = re.search(rb'charset=["\']?([\w-]+)', raw[:4096], re.I)
    if match:
        try:
            html = raw.decode(match.group(1).decode("ascii", "ignore"), errors="replace")
        except (LookupError, UnicodeDecodeError):
            html = None
    if html is None:
        for enc in ("utf-8", "utf-8-sig", "gb18030", "big5", "shift_jis", "cp1252"):
            try:
                html = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    if html is None:
        html = raw.decode("utf-8", errors="replace")

    base = "file://" + urllib.parse.quote(os.path.abspath(path))
    return html, base


# --------------------------------------------------------------------------
# Stage 1 — strip the page furniture
# --------------------------------------------------------------------------

def _gone(el) -> bool:
    """
    True if a previous decompose() already removed this node.

    find_all() hands back a snapshot, so by the time we reach an element its
    ancestor may already have been destroyed — touching it would raise.
    """
    if el is None or not isinstance(el, Tag):
        return True
    if getattr(el, "decomposed", False):
        return True
    return el.attrs is None


def _matches(el: Tag, pattern: re.Pattern) -> bool:
    if _gone(el):
        return False
    tokens = " ".join(
        [el.get("id") or ""] + list(el.get("class") or []) + [el.get("role") or ""]
    )
    return bool(tokens.strip()) and bool(pattern.search(tokens))


def _kill(elements) -> None:
    for el in elements:
        if not _gone(el):
            el.decompose()


def _prose_heavy(el: Tag) -> bool:
    """
    True if an element holds enough real prose that a class/id-token match
    is more likely a coincidence than genuine chrome.

    A short "main-nav" div is furniture. A three-thousand-word article whose
    ancestor happens to carry a utility class like "main-menu-disabled" — a
    client-side feature flag, not a menu — is not, and matching on substrings
    of hyphen-joined class names makes that kind of coincidence common on
    real sites: MediaWiki's Vector skin puts "vector-toc-available" and
    "...-main-menu-disabled" on <html> itself, which without this guard
    matches "toc" and "menu" and deletes the entire document.
    """
    return len(el.get_text(strip=True)) > 900 and el.find("p") is not None


def _strip_global(soup: BeautifulSoup) -> None:
    _kill(soup.find_all(list(DROP_TAGS)))

    # HTML comments are invisible on the live web and never legitimate
    # content, but bs4's Comment is a NavigableString subclass — so any later
    # pass that walks loose text nodes to promote them into paragraphs (see
    # _promote_text_blocks) treats a comment exactly like real prose. On a
    # real MediaWiki page this turned an internal cache-key comment
    # ("<!-- Post-processing cache key enwiki:postproc-parsoid-pcache:... -->")
    # into a genuine, visible <p> in the rendered PDF, and inflated the
    # reported word count with debug text nobody wrote and nobody sees on the
    # actual site. Removing every comment here, before any later pass can
    # mistake one for prose, closes the whole class of bug rather than one
    # call site.
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    for el in soup.find_all(attrs={"aria-hidden": "true"}):
        # aria-hidden on a big text container is usually a duplicated mobile view.
        if not _gone(el) and len(el.get_text(strip=True)) < 4000:
            el.decompose()

    for role in ("navigation", "banner", "complementary", "search", "contentinfo", "dialog"):
        _kill(soup.find_all(attrs={"role": role}))

    _kill(soup.find_all(["nav", "aside"]))

    # Honour the page's own "hide when printing" markup. A publisher marks
    # something print-hidden when a print-visible equivalent exists or the
    # content does not belong on paper: share bars, cookie prompts, and the
    # "more from this site" rails below the article all carry it.
    #
    # The one exception is a node that is essentially just an image — a hero or
    # figure the site hides only because it has a separate print copy, or to
    # save a reader's ink. Those are left for the image de-dup and icon/size
    # filters to judge, which they do better. Share bars carry no image; the
    # recommendation rails carry paragraphs of link text — both still go.
    for el in soup.find_all(True):
        if _gone(el) or el.name in ("html", "body"):
            continue
        if not _matches(el, PRINT_HIDDEN):
            continue
        if el.find("img") and len(el.get_text(strip=True)) < 200:
            continue
        el.decompose()

    # <footer> and <header> only go if they sit outside an <article>.
    for el in soup.find_all(["footer", "header"]):
        if not _gone(el) and not el.find_parent("article"):
            el.decompose()

    for el in soup.find_all(True):
        if _gone(el):
            continue
        # <html> and <body> are the document's own roots, never a genuine nav
        # bar or cookie banner — a class-token match here is always a false
        # positive, and decomposing either one destroys the whole document.
        if el.name in ("html", "body"):
            continue
        if _matches(el, STRUCTURAL_JUNK) and not _prose_heavy(el):
            el.decompose()

    _kill(soup.find_all(style=re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)))
    _kill(soup.find_all(hidden=True))


# --------------------------------------------------------------------------
# Stage 2 — find the article container
# --------------------------------------------------------------------------

def _link_density(node: Tag, text_len: int) -> float:
    if text_len == 0:
        return 1.0
    link_len = sum(len(a.get_text(" ", strip=True)) for a in node.find_all("a"))
    return min(link_len / text_len, 1.0)


def _score(node: Tag) -> float:
    """Rough heuristic: lots of prose, few links, semantic tag = probably the article."""
    text = node.get_text(" ", strip=True)
    n = len(text)
    if n < 250:
        return 0.0

    density = _link_density(node, n)
    if density > 0.55:
        return 0.0

    paragraphs = [p for p in node.find_all("p") if len(p.get_text(strip=True)) > 40]
    if not paragraphs:
        return 0.0

    score = n * (1.0 - density)
    score += len(paragraphs) * 45
    score += len(node.find_all(["h2", "h3", "h4"])) * 25
    score += len(node.find_all(["blockquote", "figure", "pre", "table"])) * 20
    # Comma count is a decent proxy for real prose vs. lists of links.
    score += text.count(",") * 3

    if node.name == "article":
        score *= 1.5
    elif node.name == "main" or node.get("role") == "main":
        score *= 1.35
    elif node.name in ("body", "html"):
        score *= 0.6

    tokens = " ".join([node.get("id") or ""] + list(node.get("class") or []))
    if re.search(r"(^|[-_\s])(article|post|entry|story|content|main|body|text|prose|rich-text)", tokens, re.I):
        score *= 1.25

    return score


def _find_content_root(soup: BeautifulSoup) -> Tag:
    body = soup.body or soup
    candidates = body.find_all(["article", "main", "section", "div", "td"])
    candidates.append(body)

    scored = [(c, _score(c)) for c in candidates]
    scored = [(c, s) for c, s in scored if s > 0]
    if not scored:
        return body

    scored.sort(key=lambda pair: pair[1], reverse=True)
    best, best_score = scored[0]

    # A wrapper div often scores the same as the article it contains. Prefer the
    # tighter, deeper node when it holds essentially the same prose.
    best_paras = len(best.find_all("p"))
    for node, score in scored[1:8]:
        if node in best.descendants and score >= best_score * 0.92:
            if len(node.find_all("p")) >= best_paras * 0.9:
                best, best_score, best_paras = node, score, len(node.find_all("p"))

    return best


def _clean_content(root: Tag) -> None:
    """Second, gentler sweep — now that we know this is the article."""
    for el in root.find_all(True):
        if _gone(el):
            continue
        if _matches(el, INLINE_JUNK):
            # A heading inside means we probably matched a real section name
            # like "Related concepts" in an explainer; keep it if it's prose-heavy.
            if _prose_heavy(el):
                continue
            el.decompose()

    _strip_heading_furniture(root)
    _strip_footnote_markers(root)
    _strip_toc(root)


def _strip_heading_furniture(root: Tag) -> None:
    """Remove the 'edit' / '¶' permalinks that sites hang off their headings."""
    for h in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if _gone(h):
            continue
        for a in h.find_all("a"):
            if JUNK_ANCHOR_TEXT.match(a.get_text(" ", strip=True)):
                a.decompose()
        # Some themes wrap the marker in a span with no useful class.
        text = h.get_text(" ", strip=True)
        cleaned = re.sub(r"\s*\[?\s*edit(\s+source)?\s*\]?\s*$", "", text, flags=re.I)
        if cleaned != text:
            h.clear()
            h.append(cleaned)


def _strip_footnote_markers(root: Tag) -> None:
    """
    Drop citation superscripts like [1] that point at footnotes we aren't
    carrying over. Matched by their link target, so real superscripts (x²) stay.
    """
    for sup in root.find_all("sup"):
        if _gone(sup):
            continue
        classes = " ".join(sup.get("class") or [])
        links = sup.find_all("a")
        points_at_note = any(
            re.match(r"#(cite|fn|note|ref|footnote|endnote)", a.get("href") or "", re.I)
            for a in links
        )
        if points_at_note or re.search(r"reference|footnote|citation", classes, re.I):
            sup.decompose()


def _strip_toc(root: Tag) -> None:
    """
    Remove a table of contents that survived by having no useful class:
    a 'Contents' heading followed by a list that is almost entirely links.
    """
    for h in root.find_all(["h2", "h3", "h4"]):
        if _gone(h):
            continue
        if not re.match(r"^\s*(contents|table of contents|in this article|jump to)\s*$",
                        h.get_text(" ", strip=True), re.I):
            continue
        nxt = h.find_next_sibling()
        if nxt is not None and nxt.name in ("ul", "ol"):
            text_len = len(nxt.get_text(" ", strip=True))
            if text_len and _link_density(nxt, text_len) > 0.7:
                nxt.decompose()
                h.decompose()

    # Any remaining list that is nothing but internal anchors is navigation.
    for lst in root.find_all(["ul", "ol"]):
        if _gone(lst):
            continue
        items = lst.find_all("li", recursive=False)
        if len(items) < 3:
            continue
        anchors = [a for a in lst.find_all("a") if (a.get("href") or "").startswith("#")]
        if len(anchors) >= len(items) and len(lst.get_text(strip=True)) < 500:
            lst.decompose()


def _adopt_captions(root: Tag) -> None:
    """
    Pull caption text into the <figure> it describes.

    Many CMSes put the caption in a sibling div, which would otherwise print as
    a stray body paragraph — and, worse, could be split onto the page after the
    image it belongs to.
    """
    for el in list(root.find_all(["div", "p", "span", "figcaption"])):
        if _gone(el) or el.name == "figcaption":
            continue
        if not _matches(el, CAPTION_HINT):
            continue

        text = el.get_text(" ", strip=True)
        if not text or len(text) > 600:
            continue

        # Find the image this caption belongs to: inside the same wrapper,
        # or immediately before/after in the document.
        img = None
        for scope in (el.parent, el.parent.parent if el.parent else None):
            if scope is not None and not _gone(scope):
                found = scope.find("img")
                if found is not None:
                    img = found
                    break
        if img is None:
            sib = el.find_previous_sibling()
            if sib is not None and sib.find("img"):
                img = sib.find("img")
        if img is None:
            continue

        cap = BeautifulSoup("<figcaption></figcaption>", "html.parser").figcaption
        cap.string = text
        el.decompose()

        fig = img.find_parent("figure")
        if fig is not None:
            if fig.find("figcaption") is None:
                fig.append(cap)
        else:
            new_fig = BeautifulSoup('<figure class="w2p-figure"></figure>',
                                    "html.parser").figure
            img.replace_with(new_fig)
            new_fig.append(img)
            new_fig.append(cap)


# --------------------------------------------------------------------------
# Stage 3 — normalise the structure
# --------------------------------------------------------------------------

def _strip_attrs(root: Tag) -> None:
    for el in root.find_all(True):
        allowed = KEEP_ATTRS.get(el.name, set())
        for attr in list(el.attrs):
            if attr not in allowed:
                del el[attr]
        # Only our own classes survive; site classes mean nothing to our CSS.
        if "class" in el.attrs:
            el["class"] = [c for c in el["class"] if c.startswith("w2p-")]
            if not el["class"]:
                del el["class"]


def _simplify_inline(root: Tag) -> None:
    swaps = {"b": "strong", "i": "em", "u": "em"}
    for old, new in swaps.items():
        for el in root.find_all(old):
            el.name = new
    for name in ("span", "font", "tt", "big", "small", "label", "bdi", "bdo", "abbr", "time", "mark", "s", "del"):
        for el in root.find_all(name):
            el.unwrap()


def _drop_empty(root: Tag) -> None:
    """Remove nodes with no text and no image — usually layout scaffolding."""
    for _ in range(4):  # repeat: emptying a child can empty its parent
        removed = False
        for el in root.find_all(["p", "div", "section", "li", "blockquote", "figure",
                                 "span", "h1", "h2", "h3", "h4"]):
            if _gone(el) or el.find(["img", "hr", "table", "pre"]):
                continue
            text = el.get_text().replace("\xa0", " ").strip()
            if not text:
                el.decompose()
                removed = True
        if not removed:
            break
    for hr in root.find_all("hr"):
        # Trailing/leading rules add nothing once the furniture is gone.
        if hr.find_next_sibling() is None or hr.find_previous_sibling() is None:
            hr.decompose()


def _promote_text_blocks(root: Tag) -> None:
    """Turn div-wrapped prose into real paragraphs, then unwrap the leftover divs."""
    for div in root.find_all(["div", "section", "article", "main", "header", "footer", "details", "summary"]):
        if div is root:
            continue
        has_block_child = any(
            isinstance(c, Tag) and c.name in BLOCK_TAGS for c in div.children
        )
        if not has_block_child and div.get_text(strip=True):
            div.name = "p"
            div.attrs = {}

    # Any div still standing is pure scaffolding.
    for div in root.find_all(["div", "section", "article", "main", "header", "footer", "details", "summary"]):
        if div is not root:
            div.unwrap()

    # Loose text sitting directly in the root needs a paragraph around it.
    for child in list(root.children):
        if isinstance(child, NavigableString) and child.strip():
            p = BeautifulSoup("<p></p>", "html.parser").p
            text = str(child).strip()
            child.replace_with(p)
            p.string = text


def _fix_lists(root: Tag) -> None:
    for li in root.find_all("li"):
        for p in li.find_all("p"):
            # A single paragraph in a list item is redundant nesting.
            if len(li.find_all("p")) == 1 and not li.find(["ul", "ol"]):
                p.unwrap()
    # A short list reads as a single unit, so keep it on one page. Long lists
    # are left breakable — forcing those onto one page would blow out the layout.
    for lst in root.find_all(["ul", "ol"]):
        if _gone(lst) or lst.find_parent(["ul", "ol"]):
            continue
        items = lst.find_all("li", recursive=False)
        if 0 < len(items) <= 5 and len(lst.get_text(" ", strip=True)) < 700:
            lst["class"] = ["w2p-tight"]

    for dl in root.find_all("dl"):
        dl.name = "ul"
        for dt in dl.find_all("dt"):
            dt.name = "li"
            strong = BeautifulSoup("<strong></strong>", "html.parser").strong
            strong.string = dt.get_text(" ", strip=True)
            dt.clear()
            dt.append(strong)
        for dd in dl.find_all("dd"):
            dd.name = "li"


def _remap_headings(root: Tag, title: str) -> None:
    """
    Re-level headings so the document reads as one coherent hierarchy.

    Sites use h1-h6 inconsistently — some articles start their sections at h3,
    others reuse h1 for every subhead. We find the shallowest level actually in
    use and slide everything up so the top section level becomes h2.
    """
    # A heading duplicating the title is redundant once we print our own.
    norm_title = re.sub(r"\W+", "", title).lower()
    for h in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if norm_title and re.sub(r"\W+", "", h.get_text()).lower() == norm_title:
            h.decompose()

    headings = root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    if not headings:
        return

    levels = sorted({int(h.name[1]) for h in headings})
    shift = levels[0] - 2  # shallowest level becomes h2
    for h in headings:
        new_level = int(h.name[1]) - shift
        h.name = "h" + str(max(2, min(4, new_level)))  # clamp to h2-h4

    # A heading with nothing under it is a label, not a section. This must
    # walk the whole document in tree order (find_next), not just the
    # heading's own siblings (find_next_sibling): several real site templates
    # — MediaWiki's Vector 2022 skin among them — wrap each heading alone in
    # its own <div class="mw-heading">, so once that div's other child (an
    # edit-section link) is stripped as chrome, the heading has no sibling of
    # its own even though the section's paragraphs immediately follow the
    # wrapper div. find_next_sibling() misjudged every one of those headings
    # as an empty label and deleted the entire section structure.
    for h in root.find_all(["h2", "h3", "h4"]):
        if h.find_next(True) is None:
            h.decompose()


def _add_heading_ids(root: Tag) -> list[tuple[int, str, str]]:
    """
    Give every section heading a stable id and return the table of contents.

    Runs after _strip_attrs, which removes the site's own ids along with
    everything else — ids from the source page are not worth keeping anyway,
    since they are frequently duplicated or generated per-request.

    The returned triples are (level, id, text). converter turns them into a
    contents list whose page numbers come from CSS target-counter(), so they
    are resolved after layout and stay correct no matter how many pages the
    contents list itself occupies.
    """
    sections: list[tuple[int, str, str]] = []
    for index, node in enumerate(root.find_all(["h2", "h3"]), start=1):
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        anchor = f"w2p-sec-{index}"
        node["id"] = anchor
        sections.append((int(node.name[1]), anchor, text))
    return sections


def _tag_lead_paragraph(root: Tag) -> None:
    """
    Mark the article's opening paragraph so the stylesheet can set it apart.

    Must run after _strip_attrs, which removes every class on the page — this is
    the one class we add ourselves, so it has to be added last.

    Only a genuine opening paragraph qualifies: the first <p> in the document,
    with enough text to be prose rather than a dateline or a byline fragment,
    and not sitting inside a figure, quotation or list.
    """
    for node in root.find_all("p"):
        if node.find_parent(["blockquote", "figure", "li", "table"]):
            continue
        if len(node.get_text(strip=True)) < 80:
            continue          # a stub, a dateline, or "Photograph by ..."
        node["class"] = ["w2p-lead"]
        return


def _wrap_tables(root: Tag) -> None:
    for table in root.find_all("table"):
        for nested in table.find_all(["div", "section", "span"]):
            nested.unwrap()
        # Give a header-less table a header row so repeats work across pages.
        if not table.find("thead"):
            first_row = table.find("tr")
            if first_row and all(c.name == "th" for c in first_row.find_all(["td", "th"])):
                thead = BeautifulSoup("<thead></thead>", "html.parser").thead
                first_row.wrap(thead)
        if table.parent.name != "figure":
            fig = BeautifulSoup('<figure class="w2p-table"></figure>', "html.parser").figure
            table.wrap(fig)


# --------------------------------------------------------------------------
# Stage 4 — images
# --------------------------------------------------------------------------

def _resolve_url(base_url: str, candidate: str) -> str:
    """
    urljoin(), except a scheme-relative reference always resolves to https.

    A URL like "//upload.wikimedia.org/..." is scheme-relative: on the live
    web it inherits whatever scheme served the containing page, which for
    anything this tool processes is always http or https. Plain urljoin()
    instead inherits the scheme of `base_url` literally — and base_url is
    "file:///path/to/saved.html" for every locally saved page, which is the
    normal, recommended way to convert a JavaScript-rendered or paywalled
    article (see the README). That turns "//upload.wikimedia.org/x.jpg" into
    "file://upload.wikimedia.org/x.jpg": a file:// URL with a bogus host
    component, which _download_image then fails to open as a local path and
    silently drops — stripping every image from the page with no warning.
    """
    if candidate.startswith("//"):
        return "https:" + candidate
    return urllib.parse.urljoin(base_url, candidate)


def _best_from_srcset(srcset: str) -> str | None:
    """Pick the highest-resolution candidate so print output stays sharp."""
    best_url, best_weight = None, -1.0
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        weight = 1.0
        if len(bits) > 1:
            descriptor = bits[1]
            try:
                if descriptor.endswith("w"):
                    weight = float(descriptor[:-1])
                elif descriptor.endswith("x"):
                    weight = float(descriptor[:-1]) * 1000
            except ValueError:
                weight = 1.0
        if weight > best_weight:
            best_url, best_weight = url, weight
    return best_url


def _resolve_src(img: Tag, base_url: str) -> str | None:
    """Dig the real URL out of src, srcset, or any of the lazy-load attributes."""
    candidates = []
    for attr in ("data-srcset", "srcset"):
        if img.get(attr):
            picked = _best_from_srcset(img[attr])
            if picked:
                candidates.append(picked)
    for attr in (
        "src", "data-src", "data-original", "data-lazy-src", "data-lazy",
        "data-hi-res-src", "data-full-src", "data-image", "data-url", "data-echo",
    ):
        if img.get(attr):
            candidates.append(img[attr])

    for cand in candidates:
        cand = cand.strip()
        if not cand or cand.startswith("data:image/gif"):
            continue
        if cand.startswith("data:"):
            return cand
        return _resolve_url(base_url, cand)
    return None


def _download_image(url: str, asset_dir: str, session: requests.Session,
                    store=None) -> str | None:
    """Save an image locally and return its path, or None if unusable."""
    cached = store.get_asset(url) if store is not None else None
    if cached is not None:
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1]
        if len(ext) > 5 or not ext:
            ext = ".png"
        path = os.path.join(
            asset_dir,
            hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:16] + ext)
        with open(path, "wb") as fh:
            fh.write(cached)
        return path

    try:
        if url.startswith("data:"):
            header, _, payload = url.partition(",")
            if "base64" not in header:
                return None
            data = base64.b64decode(payload)
            ext = mimetypes.guess_extension(header[5:].split(";")[0]) or ".png"
        elif url.startswith("file://"):
            path = urllib.parse.unquote(url[7:])
            with open(path, "rb") as fh:
                data = fh.read()
            ext = os.path.splitext(path)[1] or ".png"
        else:
            resp = session.get(url, timeout=25)
            resp.raise_for_status()
            data = resp.content
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1]
            if len(ext) > 5 or not ext:
                ext = mimetypes.guess_extension(
                    resp.headers.get("content-type", "").split(";")[0]
                ) or ".png"
    except Exception:
        return None

    if len(data) < 1200:  # tracking pixels and spacers
        return None

    # Only remote fetches are worth caching; data: and file:// URLs cost
    # nothing to re-read and would just bloat the store.
    if store is not None and not url.startswith(("data:", "file://")):
        store.put_asset(url, data)

    name = hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:16] + ext
    path = os.path.join(asset_dir, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def _process_images(root: Tag, base_url: str, asset_dir: str,
                    text_width_mm: float, text_height_mm: float,
                    warnings: list[str], store=None, cookies=None) -> int:
    """
    Download images, drop the junk, wrap survivors in <figure>, and — the part
    that matters for print — cap each image so it can never be taller than the
    page's text block. An image that fits on one page cannot be sliced in two.
    """
    session = requests.Session()
    # Images get the same browser-shaped request as the page, plus the page as
    # their referer: hotlink protection turns away an image request that looks
    # like it came from nowhere, and that is a picture silently missing from
    # the PDF rather than an error anyone sees.
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
    })
    if base_url.startswith("http"):
        session.headers["Referer"] = base_url
    jar = _as_jar(cookies)
    if jar is not None:
        session.cookies.update(jar)
    kept = 0
    seen_src: set[str] = set()

    for img in root.find_all("img"):
        alt = (img.get("alt") or "").strip()
        src = _resolve_src(img, base_url)

        if not src:
            img.decompose()
            continue

        # The same asset routinely appears more than once — a <picture> with a
        # separate mobile and desktop <img>, or a hero duplicated inside and
        # outside the article wrapper. Keep the first, drop the rest, so it does
        # not print twice in a row.
        if src in seen_src:
            img.decompose()
            continue
        seen_src.add(src)

        # Declared dimensions rule out icons before we spend a request on them.
        try:
            declared_w = int(float(img.get("width") or 0))
            declared_h = int(float(img.get("height") or 0))
        except (TypeError, ValueError):
            declared_w = declared_h = 0
        if 0 < declared_w < 150 or 0 < declared_h < 100:
            img.decompose()
            continue

        if JUNK_IMAGE_URL.search(src) and not alt:
            img.decompose()
            continue

        local = _download_image(src, asset_dir, session, store)
        if not local:
            img.decompose()
            continue

        width_px = height_px = 0
        if HAVE_PIL:
            try:
                with Image.open(local) as im:
                    width_px, height_px = im.size
            except Exception:
                pass

        # Small images are decoration, no matter what the markup claimed.
        if width_px and (width_px < 200 or height_px < 130):
            img.decompose()
            os.path.exists(local) and os.remove(local)
            continue

        img.attrs = {"src": "file://" + urllib.parse.quote(os.path.abspath(local))}
        if alt:
            img["alt"] = alt

        # Constrain tall images so they always fit within one page's text block.
        if width_px and height_px:
            rendered_h = text_width_mm * height_px / width_px
            if rendered_h > text_height_mm:
                fitted_w = text_height_mm * width_px / height_px
                img["style"] = f"width:{fitted_w:.1f}mm;"
            # Don't upscale a small image to full column width.
            elif width_px < 700:
                img["style"] = f"max-width:{min(text_width_mm, width_px * 0.26):.1f}mm;"

        # Every image lives in a figure so break-inside: avoid has something to hold.
        fig = img.find_parent("figure")
        if fig is None:
            fig = BeautifulSoup('<figure class="w2p-figure"></figure>', "html.parser").figure
            target = img
            # Lift the image out of any paragraph wrapper first.
            parent = img.parent
            if parent is not None and parent.name in ("p", "a") and len(parent.find_all(["img"])) == 1:
                if not parent.get_text(strip=True):
                    target = parent
            target.replace_with(fig)
            fig.append(img)
        else:
            fig["class"] = ["w2p-figure"]

        # Caption: an existing figcaption wins, otherwise a descriptive alt.
        cap = fig.find("figcaption")
        if cap is not None:
            cap.attrs = {}
            if not cap.get_text(strip=True):
                cap.decompose()
                cap = None
        if cap is None and alt and len(alt) > 25 and not alt.lower().startswith("image"):
            cap = BeautifulSoup("<figcaption></figcaption>", "html.parser").figcaption
            cap.string = alt
            fig.append(cap)

        kept += 1

    if kept == 0 and root.find_all("img"):
        warnings.append("No usable images found — they may be lazy-loaded by JavaScript.")
    return kept


# --------------------------------------------------------------------------
# Stage 5 — links
# --------------------------------------------------------------------------

def _handle_links(root: Tag, base_url: str, mode: str) -> list[tuple[str, str]]:
    """
    plain     — links become ordinary text (cleanest for reading on paper)
    endnotes  — superscript markers plus a numbered list at the end
    footnotes — the URL set at the foot of the page it appears on
    keep      — links stay live and underlined

    footnotes is the best of these for reading: an endnote makes you turn to
    the back of the document and find a number, whereas a footnote is already
    in your field of view. It relies on CSS GCPM (float: footnote), which
    WeasyPrint implements and browsers do not — the same reason page breaks
    behave here and not in a browser's print dialog.
    """
    endnotes: list[tuple[str, str]] = []
    seen: dict[str, int] = {}

    for a in root.find_all("a"):
        href = (a.get("href") or "").strip()
        text = a.get_text(" ", strip=True)

        if not href or href.startswith("#") or not text:
            a.unwrap()
            continue

        absolute = _resolve_url(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            a.unwrap()
            continue

        if mode == "plain":
            a.unwrap()
        elif mode == "footnotes":
            # The note floats to the foot of whichever page this lands on, so
            # no numbering is needed here: the stylesheet's footnote counter
            # numbers call and marker together.
            note = BeautifulSoup(
                '<span class="w2p-footnote"></span>', "html.parser").span
            note.string = absolute
            a.insert_after(note)
            a.unwrap()
        elif mode == "endnotes":
            if absolute in seen:
                num = seen[absolute]
            else:
                num = len(endnotes) + 1
                seen[absolute] = num
                endnotes.append((text, absolute))
            sup = BeautifulSoup(f'<sup class="w2p-ref">{num}</sup>', "html.parser").sup
            a.insert_after(sup)
            a.unwrap()
        else:  # keep
            a.attrs = {"href": absolute}

    return endnotes


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------

def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


# Languages WeasyPrint (via Pyphen) has hyphenation dictionaries for. Claiming
# a language with no dictionary is harmless — hyphenation simply switches off —
# but claiming the *wrong* one is not, so we only trust an explicit declaration.
def _extract_lang(soup: BeautifulSoup) -> str:
    """
    Work out the document language, because hyphenation depends on it.

    WeasyPrint picks a hyphenation dictionary from the `lang` attribute. The
    document used to be hardcoded to lang="en", which meant a German or French
    article was hyphenated with English patterns — breaking words mid-morpheme
    throughout justified text. Wrong hyphenation is far more visible than none.
    """
    candidates = []

    html_tag = soup.find("html")
    if html_tag:
        candidates.append(html_tag.get("lang") or html_tag.get("xml:lang") or "")

    # og:locale is "en_GB" style; Content-Language may be a comma-separated list.
    candidates.append(_meta(soup, "og:locale", "dc.language", "language"))

    http_equiv = soup.find("meta", attrs={"http-equiv": re.compile(r"^content-language$", re.I)})
    if http_equiv and http_equiv.get("content"):
        candidates.append(http_equiv["content"])

    for raw in candidates:
        tag = _normalise_lang(raw)
        if tag:
            return tag

    return "en"


def _normalise_lang(raw: str) -> str:
    """'en_GB' / 'de-DE, en' / '  FR  ' -> 'en-gb' / 'de-de' / 'fr'. '' if unusable."""
    if not raw:
        return ""
    first = re.split(r"[,;]", raw.strip())[0].strip().replace("_", "-").lower()
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", first):
        return ""
    # A bare "x-default" or similarly meaningless tag is worse than the fallback.
    if first.startswith("x-"):
        return ""
    return first


def _extract_title(soup: BeautifulSoup, root: Tag) -> str:
    title = _meta(soup, "og:title", "twitter:title", "dc.title")
    if not title:
        h1 = root.find("h1") or soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    # Trim the "… | The Site Name" suffix.
    title = re.sub(r"\s*[|–—·\-]\s*[^|–—·\-]{2,40}$", "", title).strip()
    return title or "Untitled document"


def _extract_byline(soup: BeautifulSoup) -> str:
    author = _meta(soup, "author", "article:author", "og:article:author", "dc.creator", "parsely-author")
    if not author:
        node = soup.find(attrs={"rel": "author"}) or soup.find(
            class_=re.compile(r"(^|[-_\s])(author|byline)([-_\s]|$)", re.I)
        )
        if node:
            author = node.get_text(" ", strip=True)
    author = re.sub(r"^\s*(by|words by|written by)\s+", "", author, flags=re.I).strip()
    if author.startswith("http") or len(author) > 90:
        return ""
    return author


def _extract_date(soup: BeautifulSoup) -> str:
    raw = _meta(
        soup, "article:published_time", "og:article:published_time",
        "datePublished", "publishdate", "date", "dc.date", "parsely-pub-date",
    )
    if not raw:
        t = soup.find("time")
        if t:
            raw = t.get("datetime") or t.get_text(strip=True)
    if not raw:
        return ""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
        months = ["January", "February", "March", "April", "May", "June", "July",
                  "August", "September", "October", "November", "December"]
        year, month, day = match.groups()
        try:
            return f"{int(day)} {months[int(month) - 1]} {year}"
        except (IndexError, ValueError):
            return raw[:40]
    return raw.strip()[:60]


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def extract(html: str, base_url: str, asset_dir: str, *,
            link_mode: str = "plain",
            text_width_mm: float = 160.0,
            text_height_mm: float = 195.0,
            download_images: bool = True,
            store=None,
            cookies=None) -> Article:
    """Parse raw HTML into a clean Article. `asset_dir` receives downloaded images."""
    soup = BeautifulSoup(html, "lxml")
    art = Article(source_url=base_url if base_url.startswith("http") else "")

    art.site = _meta(soup, "og:site_name", "application-name")
    if not art.site and base_url.startswith("http"):
        art.site = urllib.parse.urlparse(base_url).netloc.replace("www.", "")
    art.lang = _extract_lang(soup)
    art.byline = _extract_byline(soup)
    art.published = _extract_date(soup)
    art.excerpt = _meta(soup, "og:description", "description", "twitter:description")[:400]

    _strip_global(soup)
    root = _find_content_root(soup)
    art.title = _extract_title(soup, root)

    # Detach so later operations can't wander back up into the page chrome.
    root = root.extract()
    _clean_content(root)
    _adopt_captions(root)   # must run while class names still exist

    if download_images:
        art.images = _process_images(
            root, base_url, asset_dir, text_width_mm, text_height_mm,
            art.warnings, store, cookies,
        )
    else:
        for img in root.find_all("img"):
            img.decompose()

    art.endnotes = _handle_links(root, base_url, link_mode)

    _simplify_inline(root)
    _remap_headings(root, art.title)
    _fix_lists(root)
    _wrap_tables(root)
    _promote_text_blocks(root)
    _drop_empty(root)
    _strip_attrs(root)
    # Both of these add attributes back, so they must follow _strip_attrs.
    art.sections = _add_heading_ids(root)
    _tag_lead_paragraph(root)

    art.body_html = root.decode_contents()
    art.word_count = len(root.get_text(" ", strip=True).split())

    if art.word_count < 120:
        art.warnings.append(
            "Very little text was recovered — the page may be JavaScript-rendered "
            "or paywalled. Try saving it from your browser and converting the file."
        )
    return art
