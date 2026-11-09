#!/usr/bin/env python3
"""Build the static site into ./site from issues/*/{meta.json,content.html} and images/.

Standard library only. Usage: python3 build.py [--check]
--check also fails on dangling image references or duplicate numbers.
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
BASE = "https://newsletter.datatalks.club"
NAME = "DataTalks.Club Weekly"

CSS = """
:root{--bg:#fff;--fg:#1d2330;--muted:#677084;--line:#e3e6ec;--accent:#1f5eff;--chip:#eef2ff}
@media (prefers-color-scheme:dark){:root{--bg:#14171f;--fg:#e8eaf0;--muted:#98a0b3;--line:#2a2f3c;--accent:#7ea2ff;--chip:#222a40}}
*{box-sizing:border-box}
body.nla{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.nla a{color:var(--accent)}
.nla-wrap{max-width:760px;margin:0 auto;padding:0 16px}
.nla-top{border-bottom:1px solid var(--line);padding:14px 0;margin-bottom:24px}
.nla-top .nla-wrap{display:flex;gap:12px;align-items:baseline;justify-content:space-between;flex-wrap:wrap}
.nla-top a.brand{font-weight:700;color:var(--fg);text-decoration:none}
.nla-top span{color:var(--muted);font-size:14px}
.nla h1{font-size:28px;line-height:1.25;margin:0 0 8px}
.nla p.lead{color:var(--muted);margin:0 0 20px}
.nla input[type=search]{width:100%;padding:10px 12px;font:inherit;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);margin-bottom:8px}
.nla h2{font-size:18px;margin:28px 0 6px;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:4px}
.nla ul.list{list-style:none;margin:0;padding:0}
.nla ul.list li{display:flex;gap:12px;align-items:baseline;padding:7px 0}
.nla ul.list time{flex:0 0 5.4em;color:var(--muted);font-size:14px;font-variant-numeric:tabular-nums}
.nla ul.list a{text-decoration:none;color:var(--fg)}
.nla ul.list a:hover{color:var(--accent)}
.nla .num{background:var(--chip);color:var(--accent);border-radius:6px;padding:0 6px;font-size:13px;margin-right:6px;white-space:nowrap}
.nla-meta{color:var(--muted);font-size:14px;margin-bottom:14px}
.nla-pager{display:flex;justify-content:space-between;gap:12px;padding:20px 0 40px;font-size:15px}
.nla-pager a{max-width:48%}
.nla-foot{border-top:1px solid var(--line);padding:18px 0 40px;color:var(--muted);font-size:14px}
.nla-issue{background:#fff;color:#222;overflow-x:hidden}
.nla-issue img{max-width:100%!important;height:auto}
.nla-issue table,.nla-issue td{max-width:100%}
.nla-issue table[width],.nla-issue .templateContainer{width:100%!important;max-width:640px!important}
.nla-issue pre{white-space:pre-wrap}
.nla-issue td,.nla-issue th{box-sizing:border-box}
.nla-issue #bodyTable,.nla-issue .templateContainer{table-layout:fixed}
.nla-issue img{height:auto!important}
.nla-issue .mcnTextContentContainer,.nla-issue .mcnTextBlock{min-width:0!important}
@media (max-width:480px){.nla h1{font-size:23px}.nla ul.list li{flex-direction:column;gap:0}}
"""

JS_FILTER = """<script>
var q=document.getElementById('q');if(q){q.addEventListener('input',function(){var v=q.value.toLowerCase();
document.querySelectorAll('ul.list li').forEach(function(li){li.hidden=v&&li.textContent.toLowerCase().indexOf(v)<0});
document.querySelectorAll('h2[data-year]').forEach(function(h){var ul=h.nextElementSibling;h.hidden=!ul.querySelector('li:not([hidden])')})})}
</script>"""


def esc(s):
    return html.escape(s or "", quote=True)


def page(title, body, description="", canonical="/", extra_head=""):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{BASE}{canonical}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%231f5eff'/%3E%3Ctext x='16' y='23' font-size='20' text-anchor='middle' fill='white' font-family='sans-serif'%3ED%3C/text%3E%3C/svg%3E">
<style>{CSS}</style>{extra_head}</head>
<body class="nla">{body}</body></html>
"""


def top():
    return (f'<div class="nla-top"><div class="nla-wrap"><a class="brand" href="/">{NAME} archive</a>'
            f'<span><a href="https://datatalks.club">datatalks.club</a></span></div></div>')


def label(m):
    return f'<span class="num">#{m["number"]}</span>' if m.get("number") else ""


def load():
    issues = []
    for d in sorted((ROOT / "issues").iterdir()):
        if (d / "meta.json").exists() and (d / "content.html").exists():
            m = json.loads((d / "meta.json").read_text())
            m["_content"] = (d / "content.html").read_text()
            issues.append(m)
    issues.sort(key=lambda m: (m["date"], m.get("number") or 0, m["slug"]), reverse=True)
    return issues


def index_page(issues):
    rows, year = [], None
    for m in issues:
        y = m["date"][:4]
        if y != year:
            if year:
                rows.append("</ul>")
            rows.append(f'<h2 data-year="{y}">{y}</h2><ul class="list">')
            year = y
        rows.append(f'<li><time datetime="{m["date"]}">{m["date"][5:]}</time>'
                    f'<a href="/issues/{m["slug"]}/">{label(m)}{esc(m["title"])}</a></li>')
    rows.append("</ul>")
    body = (top() + '<main class="nla-wrap"><h1>Past issues</h1>'
            f'<p class="lead">Every issue of {NAME}, the newsletter of the DataTalks.Club community. '
            f'{len(issues)} issues, newest first. <a href="https://datatalks.club">Subscribe at datatalks.club</a>.</p>'
            '<input id="q" type="search" placeholder="Filter by title, number or year" aria-label="Filter issues">'
            + "\n".join(rows) + '</main>' + JS_FILTER)
    return page(f"{NAME}: past issues", body, f"Archive of all {NAME} newsletter issues.")


def issue_page(m, prev, nxt):
    pager = '<div class="nla-pager"><div>'
    if nxt:  # nxt is the older issue
        pager += f'<a href="/issues/{nxt["slug"]}/">&larr; {esc(nxt["title"])}</a>'
    pager += "</div><div style=\"text-align:right\">"
    if prev:
        pager += f'<a href="/issues/{prev["slug"]}/">{esc(prev["title"])} &rarr;</a>'
    pager += "</div></div>"
    head = (f'<div class="nla-wrap"><div class="nla-meta">{label(m)}{m["date"]}</div></div>')
    body = (top() + head + f'<div class="nla-issue">{m["_content"]}</div>'
            f'<div class="nla-wrap">{pager}<div class="nla-foot">This is an archived copy of an email sent on '
            f'{m["date"]}. <a href="/">All issues</a></div></div>')
    return page(f'{m["title"]} | {NAME}', body, m.get("preview", ""), f'/issues/{m["slug"]}/')


def main():
    check = "--check" in sys.argv
    issues = load()
    SITE.mkdir(exist_ok=True)
    for child in SITE.iterdir():  # keep ./site itself so a dev server keeps serving it
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    (SITE / "issues").mkdir()
    if (ROOT / "images").exists():
        shutil.copytree(ROOT / "images", SITE / "images")
    problems = []
    for i, m in enumerate(issues):
        prev = issues[i - 1] if i > 0 else None
        nxt = issues[i + 1] if i + 1 < len(issues) else None
        d = SITE / "issues" / m["slug"]
        d.mkdir()
        (d / "index.html").write_text(issue_page(m, prev, nxt))
        for ref in re.findall(r'(?:src|srcset)="(/images/[^"\s,]+)', m["_content"]):
            if not (SITE / ref.lstrip("/")).exists():
                problems.append(f'{m["slug"]}: missing {ref}')
    (SITE / "index.html").write_text(index_page(issues))
    (SITE / "404.html").write_text(page("Not found | " + NAME, top() + '<main class="nla-wrap"><h1>Page not found</h1><p><a href="/">See all issues</a></p></main>'))
    (SITE / "CNAME").write_text("newsletter.datatalks.club\n")
    (SITE / ".nojekyll").write_text("")
    (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n")
    urls = [f"{BASE}/"] + [f'{BASE}/issues/{m["slug"]}/' for m in issues]
    (SITE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    nums = [m["number"] for m in issues if m.get("number")]
    print(f"built {len(issues)} issues, {len(problems)} problems")
    for p in problems[:20]:
        print("  ", p)
    if check and problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
