"""Turn the exported Keepy Up guide (HTML) into a styled page for the Vercel site.

Usage: python3 build_guide.py <exported-guide.html>
Pictures must already be saved as vercel-site/guide/img/<widget-id>.png.
"""
import html
import re
import sys
from pathlib import Path

SITE = Path(__file__).parent / "vercel-site" / "guide"

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Keepy Up Balloon Build Guide</title>
<meta name="description" content="Step-by-step guide to building a screen-light, sensory-friendly keepy up game with a webcam, Cozmo, MiP and a projector.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Baloo+2:wght@600;700&display=swap">
<style>
:root { --bg:#F3F5F1; --card:#FFFFFF; --ink:#22312F; --muted:#5A6B68; --line:#D8DED9; --accent:#2F7E78; --tint:#E7F0EE;
  --display:"Baloo 2","Trebuchet MS",system-ui,sans-serif; --body:"Atkinson Hyperlegible",Verdana,system-ui,sans-serif; }
@media (prefers-color-scheme: dark) { :root { --bg:#141B1A; --card:#1C2524; --ink:#E4ECEA; --muted:#9DB0AC; --line:#2D3A38; --accent:#6FC2BA; --tint:#1F2E2C; color-scheme: dark; } }
body { margin:0; background:var(--bg); color:var(--ink); font-family:var(--body); font-size:17px; line-height:1.65; }
.wrap { max-width:860px; margin:0 auto; padding:28px max(16px, env(safe-area-inset-right)) 64px max(16px, env(safe-area-inset-left)); }
nav { display:flex; gap:16px; flex-wrap:wrap; font-size:15px; margin-bottom:12px; }
a { color:var(--accent); }
h1, h2, h3 { font-family:var(--display); line-height:1.15; text-wrap:balance; }
h1 { font-size:clamp(32px, 5vw, 44px); margin:8px 0 12px; }
h2 { font-size:28px; margin:44px 0 10px; padding-top:12px; border-top:1px solid var(--line); }
h3 { font-size:21px; margin:28px 0 8px; }
p, li { max-width:70ch; }
figure { margin:20px 0; background:#fff; border:1px solid var(--line); border-radius:12px; padding:10px; }
figure img { width:100%; height:auto; display:block; }
figcaption { font-size:14px; color:#5A6B68; margin-top:6px; }
.table-wrap { overflow-x:auto; margin:14px 0; border:1px solid var(--line); border-radius:10px; background:var(--card); }
table { border-collapse:collapse; width:100%; min-width:640px; font-size:15px; }
th, td { text-align:left; vertical-align:top; padding:9px 12px; border-bottom:1px solid var(--line); }
th { background:var(--tint); }
tr:last-child td { border-bottom:0; }
code, pre { font-family: ui-monospace, Menlo, monospace; font-size:14px; }
pre { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; overflow-x:auto; white-space:pre-wrap; }
ul.contains-task-list, ul:has(input[type=checkbox]) { list-style:none; padding-left:4px; }
</style>
</head>
<body>
<div class="wrap">
<nav><a href="/">Keepy Up in Motion (animations)</a><a href="#top">Top of the guide</a></nav>
<main id="top">
"""

FOOT = """
</main>
</div>
</body>
</html>
"""


def build(export_path: str) -> None:
    body = Path(export_path).read_text()

    def figure(m: re.Match) -> str:
        node, caption = m.group(1), m.group(2)
        cap = html.unescape(caption)
        img = SITE / "img" / f"{node}.png"
        if not img.exists():
            raise SystemExit(f"Missing picture for {node}: {img}")
        return (f'<figure><img src="img/{node}.png" alt="{html.escape(cap)}" loading="lazy">'
                f"<figcaption>{caption}</figcaption></figure>")

    body = re.sub(r'<figure data-embed="node/([^"]+)"><figcaption>(.*?)</figcaption></figure>', figure, body, flags=re.S)
    body = re.sub(r"<table", '<div class="table-wrap"><table', body)
    body = re.sub(r"</table>", "</table></div>", body)
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "index.html").write_text(HEAD + body + FOOT)
    print("Wrote", SITE / "index.html")


if __name__ == "__main__":
    build(sys.argv[1])
