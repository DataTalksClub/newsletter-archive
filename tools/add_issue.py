#!/usr/bin/env python3
"""Add one issue to the archive after it has been sent.

    python3 tools/add_issue.py --number 302 --date 2026-11-09 \\
        --title "Subject line of the issue" --html sent-email.html

--html takes the HTML exactly as sent (use - for stdin). The script strips
preheader junk, unsubscribe/preferences/forward links, merge tags and tracking
pixels, downloads the images into images/, and writes
issues/<slug>/{meta.json,content.html}. Then run `python3 build.py --check`
and open a PR; merging to main publishes the site.

Use --kind standalone (no --number) for sponsor stand-alones; the slug is then
<date>-<slugified title>. Existing slugs are refused unless --force is given.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean import ROOT, clean  # noqa: E402


def slugify(text, limit=60):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-") or "issue"


def local_links():
    links = {}
    for f in (ROOT / "issues").glob("*/meta.json"):
        m = json.loads(f.read_text())
        if m.get("source"):
            links[re.sub(r"^https?://", "", m["source"]).split("?")[0].rstrip("/")] = f"/issues/{m['slug']}/"
    return links


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", required=True, help="path to the sent HTML, or - for stdin")
    ap.add_argument("--title", required=True, help="subject line")
    ap.add_argument("--date", required=True, help="send date, YYYY-MM-DD")
    ap.add_argument("--number", type=int, help="issue number (weekly issues)")
    ap.add_argument("--kind", choices=["weekly", "standalone", "other"])
    ap.add_argument("--source", help="original public URL, if any")
    ap.add_argument("--force", action="store_true", help="overwrite an existing issue")
    a = ap.parse_args()

    if not re.fullmatch(r"\d{4}-\d\d-\d\d", a.date):
        ap.error("--date must be YYYY-MM-DD")
    kind = a.kind or ("weekly" if a.number else "other")
    slug = f"weekly-{a.number}" if a.number else f"{a.date}-{slugify(a.title)}"
    d = ROOT / "issues" / slug
    if d.exists() and not a.force:
        sys.exit(f"{d} exists; pass --force to overwrite")
    html = sys.stdin.read() if a.html == "-" else Path(a.html).read_text()
    body, preview, failed = clean(html, local_links(), all_hosts=True)
    d.mkdir(parents=True, exist_ok=True)
    (d / "content.html").write_text(body)
    meta = {"slug": slug, "number": a.number, "kind": kind, "title": a.title, "date": a.date,
            "preview": preview, "source": a.source}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {d.relative_to(ROOT)}")
    for u in failed:
        print("warning: image not downloaded:", u, file=sys.stderr)


if __name__ == "__main__":
    main()
