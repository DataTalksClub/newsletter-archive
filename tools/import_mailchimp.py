"""One-off backfill: import every sent DataTalks campaign from the Mailchimp API.

Reads raw/campaigns_*.json and raw/content/<id>.json (downloaded with the API key
from the DataOps secrets store; the key is never written to disk by this script)
and writes issues/<slug>/{content.html,meta.json}, images/*, coverage.json.
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean import ROOT, clean  # noqa: E402

RAW = ROOT / "raw"
ISSUES = ROOT / "issues"
LIST_NAME = "DataTalks"
WEEKLY = re.compile(r"Weekly email\s*#\s*(\d+)", re.I)


def slugify(text, limit=60):
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:limit].strip("-") or "issue"


def load_campaigns():
    campaigns = []
    for f in sorted(RAW.glob("campaigns_*.json")):
        campaigns += json.loads(f.read_text())["campaigns"]
    campaigns = [c for c in campaigns if c["recipients"].get("list_name") == LIST_NAME]
    return sorted(campaigns, key=lambda c: c["send_time"])


def assign_slugs(campaigns):
    seen = {}
    for c in campaigns:
        s = c["settings"]
        m = WEEKLY.search(s.get("title", "")) or WEEKLY.search(s.get("subject_line", ""))
        date = c["send_time"][:10]
        if m:
            n = int(m.group(1))
            seen[n] = seen.get(n, 0) + 1
            c["_number"] = n
            c["_slug"] = f"weekly-{n}" + ("" if seen[n] == 1 else f"-{'abcdefgh'[seen[n] - 1]}")
            c["_kind"] = "weekly"
        else:
            title = s.get("title") or s.get("subject_line") or "issue"
            c["_number"] = None
            c["_slug"] = f"{date}-{slugify(title)}"
            c["_kind"] = "standalone" if re.match(r"(stand-alone|blast)", title, re.I) else "other"


def local_link_map(campaigns):
    links = {}
    for c in campaigns:
        for key in ("long_archive_url", "archive_url"):
            url = c.get(key)
            if url:
                links[re.sub(r"^https?://", "", url).split("?")[0].rstrip("/")] = f"/issues/{c['_slug']}/"
    return links


def html_of(content):
    html = content.get("archive_html") or content.get("html")
    if not html and content.get("variate_contents"):
        v = content["variate_contents"][0]
        html = v.get("archive_html") or v.get("html")
    return html


def import_one(c, links):
    content = json.loads((RAW / "content" / f"{c['id']}.json").read_text())
    html = html_of(content)
    if not html:
        return c["_slug"], "no-html", []
    body, preview, failed = clean(html, links)
    d = ISSUES / c["_slug"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "content.html").write_text(body)
    s = c["settings"]
    meta = {
        "slug": c["_slug"], "number": c["_number"], "kind": c["_kind"],
        "title": s.get("subject_line") or s.get("title"),
        "date": c["send_time"][:10], "preview": preview,
        "source": c.get("long_archive_url") or c.get("archive_url"),
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return c["_slug"], "ok", failed


def main():
    campaigns = load_campaigns()
    assign_slugs(campaigns)
    links = local_link_map(campaigns)
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: import_one(c, links), campaigns))
    bad = [r for r in results if r[1] != "ok"]
    failed = [u for r in results for u in r[2]]
    print(f"imported {len(results) - len(bad)}/{len(results)}; no-html: {bad}; image failures: {len(failed)}")
    for u in failed[:20]:
        print("  image failed:", u)
    coverage = [{"slug": c["_slug"], "number": c["_number"], "kind": c["_kind"], "date": c["send_time"][:10],
                 "source": c.get("long_archive_url"), "campaign_id": c["id"]} for c in campaigns]
    (ROOT / "raw" / "coverage_api.json").write_text(json.dumps(coverage, indent=1))


if __name__ == "__main__":
    main()
