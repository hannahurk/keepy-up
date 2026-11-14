"""
Make printable AprilTags (tag36h11) for the robots.

    python make_tags.py                 # Cozmo 4 cm, MiP 5 cm  -> tags.svg
    python make_tags.py --size-cm 7     # every tag 7 cm (e.g. for a camera far away)
    python make_tags.py --png           # also save tags.png (for testing)

It also saves tags.pdf (US Letter, landscape, real size, with a spare of each
tag). Print it at 100% / "Actual size".

Open tags.svg in a web browser and print landscape at 100% scale ("Actual size", not
"Fit to page"). Measure the 10 cm check line afterwards to be sure.

The size is the width of the BLACK square. Cut along the dashed line, which
leaves the white border on. The white border matters: the camera needs it.

Stick each tag flat on top of its robot, facing straight up, with the
"FRONT" arrow pointing to the robot's front.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).parent
DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
# Tag number, robot, and black-square size in cm. Sized to fit flat on top of
# each robot (Cozmo's back, MiP's head) and to be seen from a camera about 2 m up.
# For the corner stand, 3-4 m away, print bigger tags with --size-cm.
DEFAULT_TAGS = [(1, "Cozmo", 4.0), (2, "MiP", 5.0)]


def tag_cells(tag_id):
    """8 x 8 grid of the tag, black border included. 0 = black, 1 = white."""
    return (cv2.aruco.generateImageMarker(DICTIONARY, tag_id, 8) > 127).astype(int)


def svg_tag(tag_id, label, x_mm, y_mm, size_mm):
    cells = tag_cells(tag_id)
    cell = size_mm / 8
    margin = cell  # 1-cell white border around the black square
    out = []
    cut = size_mm + 2 * margin
    out.append(
        f'<rect x="{x_mm - margin:.2f}" y="{y_mm - margin:.2f}" width="{cut:.2f}" height="{cut:.2f}" '
        f'fill="white" stroke="#999" stroke-width="0.3" stroke-dasharray="2,1.5"/>'
    )
    for r in range(8):
        for c in range(8):
            if cells[r, c] == 0:
                out.append(
                    f'<rect x="{x_mm + c * cell:.3f}" y="{y_mm + r * cell:.3f}" '
                    f'width="{cell + 0.02:.3f}" height="{cell + 0.02:.3f}" fill="black"/>'
                )
    cx = x_mm + size_mm / 2
    top = y_mm - margin
    out.append(
        f'<path d="M {cx - 4:.2f} {top - 4:.2f} L {cx:.2f} {top - 10:.2f} L {cx + 4:.2f} {top - 4:.2f} Z" fill="#444"/>'
    )
    out.append(
        f'<text x="{cx:.2f}" y="{top - 12:.2f}" font-size="4" text-anchor="middle" '
        f'font-family="Helvetica, Arial">FRONT of {label}</text>'
    )
    out.append(
        f'<text x="{cx:.2f}" y="{y_mm + size_mm + margin + 6:.2f}" font-size="4" text-anchor="middle" '
        f'font-family="Helvetica, Arial">Tag {tag_id}  ·  {label}  ·  {size_mm / 10:g} cm black square</text>'
    )
    return out


def make_pages(tags):
    """Lay tags out on landscape pages that fit both A4 and US Letter.
    tags: list of (id, label, size_mm)."""
    page_w, page_h = 279, 210
    size_mm = max(t[2] for t in tags)
    cut = size_mm + 2 * size_mm / 8  # biggest black square plus 1-cell white border
    per_row = max(1, int((page_w - 20) // (cut + 15)))
    per_page = per_row * max(1, int((page_h - 45) // (cut + 25)))
    pages = []
    for start in range(0, len(tags), per_page):
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w}mm" height="{page_h}mm" '
            f'viewBox="0 0 {page_w} {page_h}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<text x="15" y="14" font-size="5" font-family="Helvetica, Arial">'
            "Keepy Up robot tags (tag36h11). Print landscape at 100% scale.</text>",
            '<line x1="15" y1="22" x2="115" y2="22" stroke="black" stroke-width="0.6"/>',
            '<line x1="15" y1="19" x2="15" y2="25" stroke="black" stroke-width="0.6"/>',
            '<line x1="115" y1="19" x2="115" y2="25" stroke="black" stroke-width="0.6"/>',
            '<text x="120" y="23.5" font-size="4" font-family="Helvetica, Arial">'
            "this line should measure exactly 10 cm</text>",
        ]
        page_tags = tags[start:start + per_page]
        gap_x = (page_w - per_row * cut) / (per_row + 1)
        for i, (tag_id, label, tag_mm) in enumerate(page_tags):
            col, row = i % per_row, i // per_row
            x = gap_x + col * (cut + gap_x) + (cut - tag_mm) / 2
            y = 45 + row * (cut + 25) + (cut - tag_mm) / 2
            parts += svg_tag(tag_id, label, x, y, tag_mm)
        parts.append("</svg>")
        pages.append("\n".join(parts))
    return pages


def make_png(tags, dpi=300):
    """Plain raster version, used for quick detection tests."""
    px = int(round(max(t[2] for t in tags) / 25.4 * dpi))
    tiles = []
    for tag_id, _, _ in tags:
        img = cv2.aruco.generateImageMarker(DICTIONARY, tag_id, px)
        pad = px // 4
        tiles.append(cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255))
    return np.hstack(tiles)


def make_pdf(tags, path, copies=2, dpi=300):
    """Real-size US Letter landscape PDF: each tag `copies` times, with cut lines."""
    from PIL import Image, ImageDraw, ImageFont

    mm = dpi / 25.4
    page = Image.new("L", (int(11 * dpi), int(8.5 * dpi)), 255)
    d = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(4 * mm))
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(3.2 * mm))
    except OSError:
        font = small = ImageFont.load_default()

    d.text((15 * mm, 10 * mm), "Keepy Up robot tags (tag36h11). Print at 100% / Actual size, "
           "landscape. Cut on the dashed lines.", fill=0, font=font)
    y = 24 * mm
    d.line([(15 * mm, y), (115 * mm, y)], fill=0, width=int(0.6 * mm))
    for x in (15, 115):
        d.line([(x * mm, y - 3 * mm), (x * mm, y + 3 * mm)], fill=0, width=int(0.6 * mm))
    d.text((120 * mm, y - 2.5 * mm), "this line must measure exactly 10 cm", fill=0, font=small)

    items = [t for t in tags for _ in range(copies)]
    gap = 12 * mm
    cuts = [t[2] * 1.25 * mm for t in items]
    x = (page.width - sum(cuts) - gap * (len(items) - 1)) / 2
    top = 60 * mm
    for (tag_id, label, size_mm), cut in zip(items, cuts):
        size_px = int(round(size_mm * mm))
        border = (cut - size_px) / 2
        # dashed cut line
        x0, y0, x1, y1 = x, top, x + cut, top + cut
        step = 2 * mm
        n = max(1, round(cut / step))
        n += 1 - n % 2  # odd number of pieces, so every edge starts and ends with a dash
        step = cut / n
        for a in range(0, n, 2):
            s0, s1 = a * step, (a + 1) * step
            d.line([(x0 + s0, y0), (x0 + s1, y0)], fill=120, width=2)
            d.line([(x0 + s0, y1), (x0 + s1, y1)], fill=120, width=2)
            d.line([(x0, y0 + s0), (x0, y0 + s1)], fill=120, width=2)
            d.line([(x1, y0 + s0), (x1, y0 + s1)], fill=120, width=2)
        tag = cv2.aruco.generateImageMarker(DICTIONARY, tag_id, size_px)
        page.paste(Image.fromarray(tag), (int(round(x + border)), int(round(top + border))))
        cx = x + cut / 2
        d.polygon([(cx - 3 * mm, top - 3 * mm), (cx, top - 8 * mm), (cx + 3 * mm, top - 3 * mm)], fill=60)
        d.text((cx, top - 10 * mm), f"FRONT of {label}", fill=0, font=small, anchor="ms")
        d.text((cx, y1 + 7 * mm), f"Tag {tag_id} - {label}", fill=0, font=small, anchor="ms")
        d.text((cx, y1 + 12 * mm), f"{size_mm / 10:g} cm black square", fill=0, font=small, anchor="ms")
        x += cut + gap

    d.text((15 * mm, page.height - 25 * mm),
           "Tag 1 goes flat on Cozmo's back, behind its head and clear of the lift. "
           "Tag 2 goes flat on top of MiP's head.", fill=0, font=small)
    d.text((15 * mm, page.height - 19 * mm),
           "Face each tag straight up with its FRONT arrow toward the robot's front. "
           "Keep the white border. The second copy of each is a spare.", fill=0, font=small)
    page.save(path, "PDF", resolution=dpi)
    return page


def main():
    p = argparse.ArgumentParser(description="Make printable AprilTags for the robots.")
    p.add_argument("--size-cm", type=float, default=None,
                   help="Width of the black square for every tag (default: Cozmo 4, MiP 5)")
    p.add_argument("--ids", default="1,2", help="Tag numbers to print, e.g. 1,2,3")
    p.add_argument("--png", action="store_true", help="Also save tags.png")
    args = p.parse_args()

    known = {t[0]: t for t in DEFAULT_TAGS}
    tags = []
    for i in (int(i) for i in args.ids.split(",")):
        _, label, size_cm = known.get(i, (i, f"robot {i}", 5.0))
        tags.append((i, label, (args.size_cm or size_cm) * 10))

    for n, page in enumerate(make_pages(tags), start=1):
        out = HERE / ("tags.svg" if n == 1 else f"tags_{n}.svg")
        out.write_text(page)
        print(f"Saved {out}. Open it in a browser and print landscape at 100% scale.")
    pdf = HERE / "tags.pdf"
    make_pdf(tags, pdf)
    print(f"Saved {pdf}. Print at 100% / Actual size.")
    if args.png:
        png = HERE / "tags.png"
        cv2.imwrite(str(png), make_png(tags))
        print(f"Saved {png}")


if __name__ == "__main__":
    main()
