"""Build the keepy-upy Vercel site: the animations home page and the build guide.

Usage: python3 build_site.py <exported-guide.html>
  - Home page comes from keepy-up-in-motion.html (the Claude animations page).
  - Guide comes from the doc's HTML export. Its pictures must already be saved as
    vercel-site/guide/img/<widget-id>.png.
"""
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SITE = ROOT / "vercel-site"

NAV_CSS = """
html { scroll-padding-top: 76px; }
.topbar { position: sticky; top: 0; z-index: 20; background: var(--bg); border-bottom: 1px solid var(--line); }
.topbar-inner { max-width: 900px; margin: 0 auto; box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: 10px 16px; flex-wrap: wrap;
  padding: 10px max(16px, env(safe-area-inset-right, 0px)) 10px max(16px, env(safe-area-inset-left, 0px)); }
.brand { font-family: var(--display); font-weight: 700; font-size: 21px; color: var(--ink); text-decoration: none; }
.navbtns { display: flex; gap: 8px; flex-wrap: wrap; }
.navbtn { display: inline-flex; align-items: center; min-height: 44px; box-sizing: border-box; padding: 8px 18px; border-radius: 999px; border: 1px solid var(--muted); background: var(--card); color: var(--ink);
  text-decoration: none; font-family: var(--body); font-weight: 700; font-size: 15px; line-height: 1.3; }
.navbtn:hover { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); text-decoration: underline; text-underline-offset: 3px; }
.navbtn[aria-current="page"]:hover { box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent); }
.navbtn:active, .totop:active { transform: translateY(1px); }
.totop:hover { text-decoration: underline; text-underline-offset: 3px; box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent); }
.navbtn[aria-current="page"] { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.navbtn:focus-visible, .totop:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
@media (max-width: 520px) { .topbar { position: static; } html { scroll-padding-top: 12px; } }
"""


def nav(current: str) -> str:
    def btn(href: str, label: str, key: str) -> str:
        cur = ' aria-current="page"' if key == current else ""
        return f'<a class="navbtn" href="{href}"{cur}>{label}</a>'
    return ('<header class="topbar"><div class="topbar-inner">'
            '<a class="brand" href="/">Keepy Up</a>'
            '<nav class="navbtns" aria-label="Site">'
            + btn("/", "Animations", "home") + btn("/guide/", "Build guide", "guide")
            + btn("/run/", "Run it yourself", "run") + btn("/soccer/", "Floor soccer", "soccer")
            + '<a class="navbtn" href="https://github.com/hannahurk/keepy-up">Code on GitHub <span aria-hidden="true">&#8599;</span></a>' +
            "</nav></div></header>\n")


SAFETY_HTML = """<div class="safety">
<p class="safety-lead"><strong>The robots don't see people.</strong> The ceiling camera tracks only the balloon and the two robots. It doesn't see people or children at all, so the robots won't slow down or stop for anyone. A grown-up watching is the safety system.</p>
<h3>Rules for families</h3>
<ul>
<li><strong>A grown-up always watches,</strong> within reach of the laptop, and can stop the game at any moment.</li>
<li><strong>Keep hands and feet clear.</strong> Keep small children's hands and feet out of the robots' way, and nobody sits or lies in the arena while the robots are moving.</li>
<li><strong>Floor soccer: stay outside the arena.</strong> The people kneel behind their own goal line and only reach in with their hands and arms. Nobody steps into the arena.</li>
<li><strong>Flat floor only, never a table.</strong> MiP can't sense edges, and Cozmo's own edge stop is switched off, because it stopped him wrongly on the arena floor.</li>
<li><strong>Nothing else on the arena floor,</strong> such as toys or shoes. The camera can mistake green or pink things for a robot.</li>
<li><strong>Look after MiP.</strong> MiP is a balancing robot and can tip over. Keep its battery charged (the game screen warns in red under 25%) and give it room.</li>
<li><strong>Popped balloons</strong> are a choking risk for children under 8. Pick up the pieces straight away.</li>
</ul>
<h3>How to stop the robots</h3>
<p>Each of these stops the robots' wheels at once:</p>
<ul>
<li>Press <kbd>Q</kbd>, or say "stop".</li>
<li>Press <kbd>P</kbd> to pause both robots and the scoreboard. Press <kbd>P</kbd> again, or say "start", to carry on.</li>
<li>Press <kbd>Ctrl</kbd>+<kbd>C</kbd>, or close the game window.</li>
<li>If the game program itself closes unexpectedly, the robot program stops the robots on its own.</li>
</ul>
<p class="small">The keys and voice commands are on the floor soccer game screen. Keepy uppy runs from Terminal for now: press <kbd>Ctrl</kbd>+<kbd>C</kbd> there.</p>
<h3>What the robots do by themselves</h3>
<ul>
<li><strong>Wait for the start.</strong> The robots don't move until the start sequence ends: "Get ready...", 1, 2, 3, START! With Cozmo playing, they also wait until he has been moved off his charger.</li>
<li><strong>Go slowly.</strong> Both robots top out at 0.20 m/s, about 20 cm a second.</li>
<li><strong>Stay inside the tape.</strong> They aim at least 20 cm inside the taped border, and drive straight back in if they ever end up outside it.</li>
<li><strong>Keep apart.</strong> A robot won't drive toward the other one when they're close (within 35 cm), and neither does within 20 cm. In simulation they never got closer than 19 cm.</li>
<li><strong>Stop when they can't see.</strong> A robot stops if the camera loses sight of it, or of the balloon, for half a second, or if the camera stops sending. When it's hidden under the balloon, it waits.</li>
<li><strong>MiP's Bluetooth.</strong> If it drops, MiP stops where it is and reconnects by itself.</li>
</ul>
<p class="small">These describe floor soccer, the game played with the real robots so far. Keepy uppy uses the same stops when a robot or the balloon is out of sight and the same arena limits, with a lower top speed (0.10 m/s), and hasn't been played with the real robots yet.</p>
<h3>Calm and sensory-friendly</h3>
<ul>
<li><strong>Quiet sounds.</strong> The robots' voices and the sound effects are short and kept low, with no sudden loud noises. The game sounds play through the laptop, so the grown-up controls the volume.</li>
<li><strong>No flashing lights.</strong></li>
</ul>
<h3>Privacy</h3>
<ul>
<li>Everything runs offline on the laptop: no internet is needed once it's set up.</li>
<li>Voice commands only listen for "start" and "stop", and nothing is recorded.</li>
<li>The ceiling camera's pictures are never saved, and Cozmo's own camera is off.</li>
<li>The game keeps short text logs on the laptop. They're never sent anywhere.</li>
</ul>
</div>
"""

SAFETY_CSS = """
.safety { display:block; }
.safety h3 { font-family:var(--display); font-size:20px; margin:22px 0 6px; }
.safety ul { margin:6px 0; padding-left:22px; }
.safety li { margin:6px 0; }
.safety .small { font-size:15px; color:var(--muted); }
.safety-lead { margin:6px 0 4px; padding:14px 18px; border-left:6px solid var(--accent); border-radius:10px; background:var(--card); border-top:1px solid var(--line); border-right:1px solid var(--line); border-bottom:1px solid var(--line); }
.safety kbd { font-family:ui-monospace, Menlo, monospace; font-size:14px; padding:1px 7px; border:1px solid var(--muted); border-bottom-width:2px; border-radius:6px; background:var(--card); white-space:nowrap; }
"""


def build_home() -> None:
    src = (ROOT / "keepy-up-in-motion.html").read_text()
    i = src.index('<div class="wrap">')
    head, body = src[:i], src[i:]
    body = body.replace("<!-- SAFETY -->", SAFETY_HTML)
    page = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            "<meta name=\"description\" content=\"Animated preview of a sensory keepy up game where Cozmo and MiP follow the balloon and a projected line traces its path.\">\n"
            "<style>body{margin:0}" + NAV_CSS + SAFETY_CSS + "</style>\n" + head +
            "</head>\n<body>\n" + nav("home") + body + "\n</body>\n</html>\n")
    (SITE / "index.html").write_text(page)


GUIDE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Keepy Up Balloon Build Guide</title>
<meta name="description" content="Step-by-step guide to building a sensory-friendly keepy up game where Cozmo and MiP follow the balloon, with a webcam and a projected wall drawing.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Baloo+2:wght@600;700&display=swap">
<style>
:root { --bg:#F3F5F1; --card:#FFFFFF; --ink:#22312F; --muted:#5A6B68; --line:#D8DED9; --accent:#2F7E78; --accent-ink:#FFFFFF; --tint:#E7F0EE;
  --display:"Baloo 2","Trebuchet MS",system-ui,sans-serif; --body:"Atkinson Hyperlegible",Verdana,system-ui,sans-serif; }
@media (prefers-color-scheme: dark) { :root { --bg:#141B1A; --card:#1C2524; --ink:#E4ECEA; --muted:#9DB0AC; --line:#2D3A38; --accent:#6FC2BA; --accent-ink:#0E1716; --tint:#1F2E2C; color-scheme: dark; } }
body { margin:0; background:var(--bg); color:var(--ink); font-family:var(--body); font-size:17px; line-height:1.65; }
.wrap { max-width:860px; margin:0 auto; box-sizing:border-box; padding:20px max(16px, env(safe-area-inset-right, 0px)) 96px max(16px, env(safe-area-inset-left, 0px)); }
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
code, pre { font-family:ui-monospace, Menlo, monospace; font-size:14px; }
pre { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; overflow-x:auto; white-space:pre-wrap; }
.totop { position:fixed; z-index:30; right:max(16px, calc(env(safe-area-inset-right, 0px) + 16px)); bottom:calc(16px + env(safe-area-inset-bottom, 0px));
  min-height:44px; padding:11px 18px; border-radius:999px; border:2px solid var(--accent-ink); background:var(--accent); color:var(--accent-ink); font:inherit; font-weight:700; font-size:15px;
  cursor:pointer; box-shadow:0 2px 10px rgba(0,0,0,.18); }
.download { margin:14px 0 6px; }
.dlbtn { display:inline-flex; align-items:center; gap:8px; min-height:44px; box-sizing:border-box; padding:10px 20px; border-radius:999px; border:1px solid var(--accent);
  background:var(--accent); color:var(--accent-ink); font-weight:700; font-size:16px; text-decoration:none; }
.dlbtn:hover { text-decoration:underline; text-underline-offset:3px; box-shadow:0 0 0 2px var(--bg), 0 0 0 4px var(--accent); }
.dlbtn:active { transform:translateY(1px); }
.dlbtn:focus-visible { outline:3px solid var(--accent); outline-offset:3px; }
""" + NAV_CSS + """
</style>
</head>
<body>
"""

GUIDE_FOOT = """
</main>
<button id="toTop" class="totop" type="button" hidden>&uarr; Back to top</button>
<script>
(function(){
  var b = document.getElementById('toTop');
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  function check(){ b.hidden = window.scrollY < 600; }
  window.addEventListener('scroll', check, {passive: true});
  b.addEventListener('click', function(){ window.scrollTo({top: 0, behavior: reduce ? 'auto' : 'smooth'}); document.querySelector('.brand').focus({preventScroll: true}); });
  check();
})();
</script>
</body>
</html>
"""


TAGS_URL = "https://keepy-upy.vercel.app/guide/tags.pdf"
TAGS_BLOCK = """
<p class="download"><a class="dlbtn" href="tags.pdf" download="keepy-up-robot-tags.pdf">&darr; Download the robot tags (PDF, 1 page)</a></p>
<figure><img src="img/tags-preview.png" alt="The printable tag sheet: two copies of tag 1 for Cozmo (4 cm) and two of tag 2 for MiP (5 cm), each with a FRONT arrow, a dashed cut line, and a 10 cm check line at the top." loading="lazy">
<figcaption>The robot tags sheet. Print it landscape at 100%, then check the top line measures 10 cm.</figcaption></figure>
"""


def add_tags_download(body: str, guide: Path) -> str:
    """Put a download button and a preview of the tag sheet under the step that links to it."""
    if TAGS_URL not in body:
        return body
    for f in ("tags.pdf", "img/tags-preview.png"):
        if not (guide / f).exists():
            raise SystemExit(f"Missing {guide / f}")
    body = body.replace(f'href="{TAGS_URL}"', 'href="tags.pdf"')
    i = body.index('href="tags.pdf"')
    end = body.index("</p>", i) + len("</p>")
    return body[:end] + TAGS_BLOCK + body[end:]


def build_guide(export_path: str) -> None:
    body = Path(export_path).read_text()
    guide = SITE / "guide"

    def figure(m: re.Match) -> str:
        node, caption = m.group(1), m.group(2)
        if not (guide / "img" / f"{node}.png").exists():
            raise SystemExit(f"Missing picture for {node}")
        alt = html.escape(html.unescape(caption))
        return (f'<figure><img src="img/{node}.png" alt="{alt}" loading="lazy">'
                f"<figcaption>{caption}</figcaption></figure>")

    body = re.sub(r'<figure data-embed="node/([^"]+)"><figcaption>(.*?)</figcaption></figure>', figure, body, flags=re.S)
    body = body.replace("<table", '<div class="table-wrap"><table').replace("</table>", "</table></div>")
    body = add_tags_download(body, guide)
    page = GUIDE_HEAD + nav("guide") + '<div class="wrap"><main id="top">\n' + body + "\n</div>" + GUIDE_FOOT
    page = page.replace("\n</div>\n</main>", "\n</main>\n</div>")
    (guide / "index.html").write_text(page)


RUN_CSS = """
.lead { font-size:19px; }
.small { font-size:15px; color:var(--muted); }
.wip { margin:20px 0; padding:14px 18px; border:1px solid var(--line); border-left:6px solid var(--accent); border-radius:10px; background:var(--tint); }
.wip p, .wip li { margin:6px 0; }
.wip ul { padding-left:20px; margin:6px 0 10px; }
.wip-title { font-family:var(--display); font-weight:700; font-size:22px; margin:0 0 4px !important; }
.toc { margin:20px 0; padding:12px 18px; border:1px solid var(--line); border-radius:10px; background:var(--card); }
.toc-title { font-weight:700; margin:0 0 4px; }
.toc ol { margin:0; padding-left:22px; columns:2 240px; column-gap:28px; }
.toc li { margin:3px 0; break-inside:avoid; }
kbd { font-family:ui-monospace, Menlo, monospace; font-size:14px; padding:1px 7px; border:1px solid var(--muted); border-bottom-width:2px; border-radius:6px; background:var(--card); white-space:nowrap; }
details { margin:16px 0; padding:10px 16px; border:1px solid var(--line); border-radius:10px; background:var(--card); }
summary { cursor:pointer; font-weight:700; min-height:28px; }
summary:hover { text-decoration:underline; text-underline-offset:3px; }
summary:focus-visible { outline:3px solid var(--accent); outline-offset:3px; }
figure.svgfig { background:var(--card); }
figure.svgfig svg { width:100%; height:auto; display:block; }
.tagfigs { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:0 14px; }
.tagfigs figure { margin:10px 0; }
svg .lbl { font-family:var(--body); font-size:14px; fill:var(--ink); }
svg .muted { fill:var(--muted); }
svg .num { font-family:var(--display); font-weight:700; font-size:22px; fill:var(--accent); }
svg .area { fill:var(--tint); stroke:var(--accent); stroke-width:2; stroke-dasharray:6 5; }
svg .half { stroke:var(--muted); stroke-width:2; stroke-dasharray:4 5; }
svg .cross path { stroke:var(--accent); stroke-width:4; stroke-linecap:round; fill:none; }
svg .dim { stroke:var(--muted); stroke-width:1.5; }
svg .you { fill:var(--muted); }
svg .cam rect { fill:var(--muted); }
svg .ray { stroke:var(--muted); stroke-width:2; fill:none; stroke-linecap:round; }
svg .robot { fill:#FFFFFF; stroke:#5A6B68; stroke-width:2; }
svg .trk, svg .wheel { fill:#3A3A3A; stroke:#3A3A3A; stroke-width:2; }
svg .hub { fill:#A89A8C; }
svg .face { fill:#1B2A44; }
svg .visor { fill:none; stroke:#1B2A44; stroke-width:9; stroke-linecap:round; }
svg .lift { fill:none; stroke:#8C8C8C; stroke-width:5; stroke-linecap:round; stroke-linejoin:round; }
svg .tip { fill:#222; }
svg .tag { fill:#111; }
svg .tagwhite { fill:#FFFFFF; stroke:#5A6B68; stroke-width:1; stroke-dasharray:3 2; }
svg .arrow { fill:none; stroke:#C2410C; stroke-width:4; stroke-linecap:round; stroke-linejoin:round; }
svg .arrow.light { stroke:#FDBA74; }
:root { --tp:#7C3AED; --tk:#DB2777; --tb:#2563EB; }
@media (prefers-color-scheme: dark) { :root { --tp:#A78BFA; --tk:#F472B6; --tb:#60A5FA; } }
.wip h2.wip-title { border-top:0; padding-top:0; margin:0 0 2px; font-size:24px; }
.wip h3 { font-size:18px; margin:14px 0 4px; }
.wip ol { padding-left:22px; margin:6px 0 10px; }
ul.done { list-style:none; padding-left:4px; }
ul.done li::before { content:"\\2713"; color:var(--accent); font-weight:700; margin-right:8px; }
.sw { display:inline-block; width:14px; height:14px; border-radius:3px; margin-right:8px; vertical-align:-2px; }
.sw-purple { background:var(--tp); } .sw-pink { background:var(--tk); } .sw-blue { background:var(--tb); }
svg .sm { font-family:var(--body); font-size:12.5px; fill:var(--ink); }
svg .sm.muted { fill:var(--muted); }
svg .t-purple { fill:none; stroke:var(--tp); stroke-width:6; }
svg .t-pink { stroke:var(--tk); stroke-width:5; }
svg .t-goal { stroke:var(--tk); stroke-width:9; }
svg .t-post { stroke:var(--tk); stroke-width:6; stroke-linecap:round; fill:none; }
svg .sq-blue { fill:var(--tb); fill-opacity:.12; stroke:var(--tb); stroke-width:4; }
svg .sq-pink { fill:var(--tk); fill-opacity:.12; stroke:var(--tk); stroke-width:4; }
svg .xmark path { stroke:var(--tp); stroke-width:4; stroke-linecap:round; fill:none; }
svg .lg-purple { fill:var(--tp); } svg .lg-pink { fill:var(--tk); } svg .lg-blue { fill:var(--tb); }
svg .flow { fill:none; stroke:var(--accent); stroke-width:2.5; stroke-dasharray:7 5; stroke-linecap:round; stroke-linejoin:round; }
svg .mk-green { fill:#22A06B; stroke:#145C3D; stroke-width:1.5; }
svg .mk-pink { fill:#EC4899; stroke:#9D174D; stroke-width:1.5; }
svg .mk-blue { fill:#3B82F6; stroke:#1E3A8A; stroke-width:1.5; }
svg .lane-c { fill:var(--tint); }
svg .lane-m { fill:var(--card); }
svg .lane-split { stroke:var(--muted); stroke-width:2; stroke-dasharray:6 6; }
svg .person { fill:var(--muted); }
svg .balloon { fill:#F5C518; stroke:#A07C00; stroke-width:2; }
figure.svgfig figcaption { color:var(--muted); }
.hscroll { overflow-x:auto; }
.news { margin:8px 0 6px; }
.getcode { margin:20px 0; padding:14px 18px; border:1px solid var(--line); border-radius:10px; background:var(--card); }
.getcode h2.wip-title { border-top:0; padding-top:0; margin:0 0 4px; font-size:24px; }
.getcode p, .getcode li { margin:6px 0; }
.news-card { margin:20px 0; padding:16px 20px; border-radius:12px; background:var(--accent); color:var(--accent-ink); }
.news-card p { margin:4px 0; max-width:none; }
.news-card .news-title { font-family:var(--display); font-weight:700; font-size:24px; }
ol.countdown { list-style:none; padding:0; display:flex; flex-wrap:wrap; gap:10px; }
ol.countdown li { margin:0; padding:8px 16px; border:1px solid var(--line); border-radius:999px; background:var(--card); font-weight:700; }
ol.countdown li:last-child { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
svg .reach { stroke:var(--accent); stroke-width:3; stroke-dasharray:3 6; stroke-linecap:round; }
.anim { margin:24px 0; }
.anim h2 { margin-top:24px; }
.sb { display:flex; align-items:baseline; justify-content:center; gap:14px; margin:14px 0 2px; font-family:var(--display); }
.sb b { font-size:56px; line-height:1; min-width:1.2em; text-align:center; color:var(--accent); }
.sb-team { font-size:20px; font-weight:700; } .sb-dash { font-size:36px; color:var(--muted); }
.sb-msg { text-align:center; font-weight:700; font-size:20px; min-height:1.6em; margin:0 auto 4px; }
.anim-fig { margin-top:6px; }
.anim-fig .hscroll svg { min-width:0; }
svg .bigmsg { font-family:var(--display); font-weight:700; font-size:54px; fill:var(--accent); stroke:var(--card); stroke-width:6; paint-order:stroke; }
svg .p-body { fill:var(--muted); } svg .p-head { fill:var(--ink); }
svg .lift-s { fill:none; stroke:#8C8C8C; stroke-width:3; stroke-linecap:round; }
.ctl { display:flex; gap:10px; flex-wrap:wrap; margin:10px 0 4px; }
.ctlbtn { min-height:44px; padding:8px 20px; border-radius:999px; border:1px solid var(--muted); background:var(--card); color:var(--ink); font:inherit; font-weight:700; cursor:pointer; }
.ctlbtn:hover { border-color:var(--accent); box-shadow:inset 0 0 0 1px var(--accent); text-decoration:underline; text-underline-offset:3px; }
.ctl-primary { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
.ctl-primary:hover { box-shadow:0 0 0 2px var(--bg), 0 0 0 4px var(--accent); }
.ctlbtn:active { transform:translateY(1px); }
.ctlbtn:focus-visible { outline:3px solid var(--accent); outline-offset:2px; }
.anim-cap { min-height:3.2em; color:var(--ink); }
svg .kneel ellipse { fill:var(--muted); } svg .khead { fill:var(--ink); } svg .karm { stroke:var(--muted); stroke-width:7; stroke-linecap:round; }
svg .k-arm { stroke:var(--muted); stroke-width:7; stroke-linecap:round; } svg .k-hand { fill:var(--ink); }
.hscroll svg { min-width:560px; }
"""

PAGES = {
    "run": ("run-it-yourself.html", "run", "Run Keepy Up Yourself",
            "How to set up and run the Keepy Up software: ceiling camera, taped arena, robot markers, balloon colour, robot tests and both games. Work in progress."),
    "soccer": ("floor-soccer.html", "soccer", "Floor Soccer with Robots",
               "Floor soccer on the Keepy Up arena: two people against Cozmo and MiP, air-hockey style, with an automatic scorekeeper. Rules, robot defence and how to run it."),
}


def build_page(key: str) -> None:
    src, folder, title, desc = PAGES[key]
    body = (ROOT / src).read_text().replace("<!-- SAFETY -->", SAFETY_HTML)
    head = (GUIDE_HEAD
            .replace("<title>Keepy Up Balloon Build Guide</title>", f"<title>{title}</title>")
            .replace('content="Step-by-step guide to building a sensory-friendly keepy up game where Cozmo and MiP follow the balloon, with a webcam and a projected wall drawing."',
                     f'content="{desc}"')
            .replace("</style>", RUN_CSS + SAFETY_CSS + "</style>"))
    page = (head + nav(key) + '<div class="wrap"><main id="top">\n' + body +
            "\n</main>\n</div>" + GUIDE_FOOT.replace("\n</main>", "", 1))
    out = SITE / folder
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(page)


if __name__ == "__main__":
    build_home()
    build_guide(sys.argv[1])
    for key in PAGES:
        build_page(key)
    print("Built the home page, guide, run and soccer pages in", SITE)
