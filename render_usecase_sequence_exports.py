from __future__ import annotations

import html
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from build_usecase_sequence_exports import DIAGRAMS, OUT, make_diagram


WIDTH, HEIGHT = 2000, 1040
FONT_PATH = r"C:\Windows\Fonts\times.ttf"
FONT_BOLD_PATH = r"C:\Windows\Fonts\timesbd.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD_PATH if bold else FONT_PATH, size)


def endpoints(element: dict, lookup: dict[str, dict] | None = None) -> tuple[float, float, float, float]:
    pts = element.get("points") or [[0, 0], [element.get("width", 0), element.get("height", 0)]]
    x1, y1 = element["x"] + pts[0][0], element["y"] + pts[0][1]
    x2, y2 = element["x"] + pts[-1][0], element["y"] + pts[-1][1]
    if lookup and element.get("startBinding") and element.get("endBinding"):
        start = lookup.get(element["startBinding"].get("elementId"))
        end = lookup.get(element["endBinding"].get("elementId"))
        if start and end:
            sx, sy = start["x"] + start["width"] / 2, start["y"] + start["height"] / 2
            ex, ey = end["x"] + end["width"] / 2, end["y"] + end["height"] / 2
            dx, dy = ex - sx, ey - sy
            def clip(shape: dict, cx: float, cy: float, vx: float, vy: float) -> tuple[float, float]:
                if shape.get("type") == "ellipse":
                    rx, ry = shape["width"] / 2, shape["height"] / 2
                    t = 1 / math.sqrt((vx / rx) ** 2 + (vy / ry) ** 2)
                    return cx + vx * t, cy + vy * t
                return cx, cy
            x1, y1 = clip(start, sx, sy, dx, dy)
            x2, y2 = clip(end, ex, ey, -dx, -dy)
    return x1, y1, x2, y2


def dashed_segments(x1: float, y1: float, x2: float, y2: float, dash: float = 8, gap: float = 6):
    length = math.hypot(x2 - x1, y2 - y1)
    if not length:
        return
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    pos = 0.0
    while pos < length:
        end = min(length, pos + dash)
        yield (x1 + ux * pos, y1 + uy * pos, x1 + ux * end, y1 + uy * end)
        pos += dash + gap


def arrow_head_svg(x1: float, y1: float, x2: float, y2: float) -> str:
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 9
    p1 = (x2 - size * math.cos(angle - math.pi / 6), y2 - size * math.sin(angle - math.pi / 6))
    p2 = (x2 - size * math.cos(angle + math.pi / 6), y2 - size * math.sin(angle + math.pi / 6))
    return f'<path d="M {p1[0]:.1f},{p1[1]:.1f} L {x2:.1f},{y2:.1f} L {p2[0]:.1f},{p2[1]:.1f}" fill="white" stroke="#000000" stroke-width="1.2"/>'


def draw_arrow_head(draw: ImageDraw.ImageDraw, x1: float, y1: float, x2: float, y2: float) -> None:
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 10
    p1 = (x2 - size * math.cos(angle - math.pi / 6), y2 - size * math.sin(angle - math.pi / 6))
    p2 = (x2 - size * math.cos(angle + math.pi / 6), y2 - size * math.sin(angle + math.pi / 6))
    draw.polygon([(x2, y2), p1, p2], fill="white", outline="black")


def svg_text(element: dict) -> str:
    raw = element.get("text", "")
    lines = raw.split("\n")
    size = element.get("fontSize", 16)
    weight = element.get("fontWeight", "normal")
    cx = element["x"] + element["width"] / 2
    cy = element["y"] + element["height"] / 2
    line_h = size * 1.25
    first_y = cy - (len(lines) - 1) * line_h / 2 + size * 0.35
    pieces = []
    for idx, line in enumerate(lines):
        pieces.append(f'<tspan x="{cx:.1f}" y="{first_y + idx * line_h:.1f}">{html.escape(line)}</tspan>')
    return f'<text x="{cx:.1f}" y="{first_y:.1f}" text-anchor="middle" font-family="Times New Roman, Times, serif" font-size="{size}px" font-weight="{weight}" fill="#000000">{"".join(pieces)}</text>'


def scene_to_svg(scene: dict) -> str:
    lookup = {e["id"]: e for e in scene["elements"]}
    body = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1040" viewBox="0 0 2000 1040">',
        '<rect width="2000" height="1040" fill="white"/>',
    ]
    for e in scene["elements"]:
        typ = e.get("type")
        if typ == "rectangle":
            body.append(f'<rect x="{e["x"]:.1f}" y="{e["y"]:.1f}" width="{e["width"]:.1f}" height="{e["height"]:.1f}" fill="white" stroke="black" stroke-width="{e.get("strokeWidth", 1):.1f}"/>')
        elif typ == "ellipse":
            body.append(f'<ellipse cx="{e["x"] + e["width"] / 2:.1f}" cy="{e["y"] + e["height"] / 2:.1f}" rx="{e["width"] / 2:.1f}" ry="{e["height"] / 2:.1f}" fill="white" stroke="black" stroke-width="{e.get("strokeWidth", 1):.1f}"/>')
        elif typ in {"line", "arrow"}:
            x1, y1, x2, y2 = endpoints(e, lookup)
            dash = ' stroke-dasharray="8,6"' if e.get("strokeStyle") == "dashed" else ""
            body.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="black" stroke-width="{e.get("strokeWidth", 1):.1f}"{dash}/>')
            if typ == "arrow":
                body.append(arrow_head_svg(x1, y1, x2, y2))
        elif typ == "text":
            body.append(svg_text(e))
    body.append("</svg>")
    return "\n".join(body) + "\n"


def draw_text(draw: ImageDraw.ImageDraw, e: dict) -> None:
    lines = e.get("text", "").split("\n")
    size = int(e.get("fontSize", 16))
    fnt = font(size, e.get("fontWeight") == "bold")
    cx = e["x"] + e["width"] / 2
    cy = e["y"] + e["height"] / 2
    line_h = size * 1.25
    total_h = line_h * len(lines)
    top = cy - total_h / 2
    for idx, line in enumerate(lines):
        box = draw.textbbox((0, 0), line, font=fnt)
        tw = box[2] - box[0]
        baseline_y = top + idx * line_h
        draw.text((cx - tw / 2, baseline_y), line, fill="black", font=fnt)


def scene_to_png(scene: dict, path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    lookup = {e["id"]: e for e in scene["elements"]}
    for e in scene["elements"]:
        typ = e.get("type")
        if typ == "rectangle":
            draw.rectangle((e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]), outline="black", width=1)
        elif typ == "ellipse":
            draw.ellipse((e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]), outline="black", width=1)
        elif typ in {"line", "arrow"}:
            x1, y1, x2, y2 = endpoints(e, lookup)
            if e.get("strokeStyle") == "dashed":
                for sx1, sy1, sx2, sy2 in dashed_segments(x1, y1, x2, y2):
                    draw.line((sx1, sy1, sx2, sy2), fill="black", width=1)
            else:
                draw.line((x1, y1, x2, y2), fill="black", width=1)
            if typ == "arrow":
                draw_arrow_head(draw, x1, y1, x2, y2)
        elif typ == "text":
            draw_text(draw, e)
    image.save(path, "PNG")


def main() -> None:
    for spec in DIAGRAMS:
        scene = make_diagram(spec)
        name = f"hinh_{spec['number'].replace('.', '_')}_usecase_{spec['slug']}"
        (OUT / f"{name}.svg").write_text(scene_to_svg(scene), encoding="utf-8")
        scene_to_png(scene, OUT / f"{name}.png")
    print(f"Rendered {len(DIAGRAMS)} SVG and PNG pairs in {OUT}")


if __name__ == "__main__":
    main()
