"""Turn a sent-email HTML document into a clean, tracking-free archive copy.

Used by tools/import_mailchimp.py (one-off backfill) and tools/add_issue.py
(one issue after each send). Requires beautifulsoup4 and lxml.
"""
import hashlib
import re
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, Comment

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "images"

# Links that only make sense for one recipient or for the sending platform.
PERSONAL_LINK = re.compile(
    r"list-manage\.com/(profile|unsubscribe|track|forward)|forward-to-friend\.com"
    r"|campaign-archive\.com|/unsubscribe|/preferences|\*\|[A-Z_:]+\|\*|\[UNIQID\]|\{\{\s*unsubscribe",
    re.I,
)
TRACKING = re.compile(r"list-manage\.com/track|open\.php|/o/\w+\.gif|\bpixel\b", re.I)
MERGE_TAG = re.compile(r"\*\|[^|]{1,40}\|\*|\[UNIQID\]")
FOOTER_TEXT = re.compile(r"copyright|all rights reserved|update your preferences|unsubscribe|view this email|our mailing address", re.I)
IMG_HOSTS = ("mcusercontent.com", "cdn-images.mailchimp.com", "gallery.mailchimp.com", "mcusercontent.com")
CSS_URL = re.compile(r"url\(\s*['\"]?(https?://[^)'\"\s]+)['\"]?\s*\)")
HIDDEN_STYLE = re.compile(r"display:\s*none|max-height:\s*0", re.I)


def fetch_image(url):
    """Download an image once into images/ (content-addressed); return its site path."""
    url = url.replace("&amp;", "&")
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    for existing in IMAGES.glob(key + ".*"):
        return "/images/" + existing.name
    req = urllib.request.Request(url, headers={"User-Agent": "newsletter-archive/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                ctype = r.headers.get_content_type()
            break
        except Exception:
            if attempt == 2:
                return None
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
           "image/svg+xml": "svg"}.get(ctype)
    if not ext:
        m = re.search(r"\.(png|jpe?g|gif|webp|svg)(?:$|\?)", url, re.I)
        ext = m.group(1).lower() if m else "img"
    IMAGES.mkdir(exist_ok=True)
    path = IMAGES / f"{key}.{ext}"
    path.write_bytes(data)
    optimize(path)
    return f"/images/{key}.{ext}"


MAX_WIDTH = 1200  # emails render at ~600px; 2x covers retina screens


def optimize(path):
    """Shrink oversized still images in place (animated GIFs are left alone)."""
    try:
        from PIL import Image
    except ImportError:
        return
    if path.suffix not in (".png", ".jpg", ".jpeg"):
        return
    try:
        with Image.open(path) as im:
            if getattr(im, "is_animated", False):
                return
            im.load()
            if im.width > MAX_WIDTH:
                im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
            before = path.stat().st_size
            tmp = path.with_suffix(path.suffix + ".tmp")
            if path.suffix == ".png":
                im.save(tmp, "PNG", optimize=True)
            else:
                im.convert("RGB").save(tmp, "JPEG", quality=85, optimize=True)
        if tmp.stat().st_size < before:
            tmp.replace(path)
        else:
            tmp.unlink()
    except Exception:
        pass


def _prune_empty(node):
    """Remove node, then any ancestor left with no text and no image."""
    parent = node.parent
    node.decompose()
    while parent is not None and parent.name not in ("body", "html", "[document]"):
        if parent.get_text(strip=True) or parent.find(["img", "a", "iframe", "video"]):
            break
        nxt = parent.parent
        parent.decompose()
        parent = nxt


def clean(html, local_links=None, download=True, all_hosts=False):
    """Return (body_html_with_styles, preview_text, failed_image_urls)."""
    local_links = local_links or {}
    soup = BeautifulSoup(html, "lxml")
    failed = []

    preview = ""
    pv = soup.find(class_="mcnPreviewText")
    if pv:
        preview = MERGE_TAG.sub("", pv.get_text(" ", strip=True)).strip()

    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for t in soup.find_all(["script", "noscript", "iframe", "form", "meta", "link", "title"]):
        t.decompose()
    for t in soup.find_all(class_=["mcnPreviewText"]):
        t.decompose()
    # Hidden preheader filler (zero-width character spam) and any hidden block.
    for t in soup.body.find_all(style=HIDDEN_STYLE):
        if t.parent is not None and not t.find("img"):
            t.decompose()
    for ident in ("templatePreheader", "templateFooter"):
        t = soup.find(id=ident)
        if t:
            t.decompose()
    for t in soup.find_all(class_="mceFooterSection"):
        t.decompose()

    # Tracking pixels: tiny images or images served from a tracker.
    for img in soup.find_all("img"):
        src = img.get("src", "")
        w, h = img.get("width", ""), img.get("height", "")
        if TRACKING.search(src) or (w == "1" and h == "1"):
            img.decompose()

    # Personal / platform links: drop the link, keep it out of the page.
    for a in soup.find_all("a", href=True):
        if PERSONAL_LINK.search(a["href"]):
            if a.get_text(strip=True) or a.find("img"):
                a.unwrap() if not a.find("img") else a.decompose()
            else:
                a.decompose()
    # Leftover footer sentences ("Copyright ... All rights reserved", "Want to change how...").
    for el in soup.body.find_all(["p", "div", "td"]):
        if el.decomposed if hasattr(el, "decomposed") else False:
            continue
        text = el.get_text(" ", strip=True)
        if text and len(text) < 400 and FOOTER_TEXT.search(text) and not el.find("img") \
                and not el.find(["p", "div", "table"]):
            _prune_empty(el)

    for a in soup.find_all("a", href=True):
        href = MERGE_TAG.sub("", a["href"])
        # Rewrite links to other archived issues to the local copy.
        key = re.sub(r"^https?://(?:www\.)?", "", href).split("?")[0].rstrip("/")
        if key in local_links:
            href = local_links[key]
        a["href"] = href
        if href.startswith("http"):
            a["rel"] = "noopener"
    for tag in soup.find_all(True):
        for attr in ("href", "src", "alt", "title", "value"):
            if tag.has_attr(attr) and isinstance(tag[attr], str) and "*|" in tag[attr]:
                tag[attr] = MERGE_TAG.sub("", tag[attr])

    # Images: download into the repo so the archive survives the Mailchimp account.
    def localize(url):
        if not download or not url.startswith("http") or not (all_hosts or any(h in url for h in IMG_HOSTS)):
            return url
        new = fetch_image(url)
        if new is None:
            failed.append(url)
            return url
        return new

    for img in soup.find_all("img"):
        if img.get("src", "").startswith("http"):
            img["src"] = localize(img["src"])
        if img.get("srcset"):
            img["srcset"] = ", ".join(
                " ".join([localize(p.split()[0])] + p.split()[1:]) for p in img["srcset"].split(",") if p.strip()
            )
        for attr in ("data-src", "data-original"):
            if img.has_attr(attr):
                del img[attr]
        img["loading"] = "lazy"
    for tag in soup.find_all(style=CSS_URL):
        tag["style"] = CSS_URL.sub(lambda m: f"url({localize(m.group(1))})", tag["style"])
    for tag in soup.find_all(background=True):
        if tag["background"].startswith("http"):
            tag["background"] = localize(tag["background"])
    for st in soup.find_all("style"):
        if st.string:
            st.string = CSS_URL.sub(lambda m: f"url({localize(m.group(1))})", st.string)
            st.string = re.sub(r"@import[^;]+;", "", st.string)

    styles = "".join(str(s) for s in soup.head.find_all("style")) if soup.head else ""
    body = "".join(str(c) for c in soup.body.children)
    return styles + body, preview, failed
