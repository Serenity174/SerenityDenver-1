"""Build the white voice-control icons. Development dependency: Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / "assets" / "voice"
SCALE = 24


def build(name, shapes):
    image = Image.new("RGBA", (24 * SCALE, 24 * SCALE))
    draw = ImageDraw.Draw(image)
    svg = []
    for kind, coordinates in shapes:
        if kind == "line":
            points = list(zip(coordinates[::2], coordinates[1::2]))
            scaled = [(round(x * SCALE), round(y * SCALE)) for x, y in points]
            draw.line(scaled, fill="white", width=round(1.6 * SCALE), joint="curve")
            for x, y in scaled:
                radius = 0.8 * SCALE
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="white")
            svg.append('<polyline points="' + " ".join(f"{x},{y}" for x, y in points) + '"/>')
        elif kind == "ellipse":
            draw.ellipse(
                tuple(round(n * SCALE) for n in coordinates),
                outline="white",
                width=round(1.6 * SCALE),
            )
            x1, y1, x2, y2 = coordinates
            svg.append(
                f'<ellipse cx="{(x1 + x2) / 2}" cy="{(y1 + y2) / 2}" '
                f'rx="{(x2 - x1) / 2}" ry="{(y2 - y1) / 2}"/>'
            )
        elif kind == "curve":
            x0, y0, x1, y1, x2, y2, x3, y3 = coordinates
            points = []
            for step in range(41):
                t = step / 40
                u = 1 - t
                points.append(
                    (
                        (u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3) * SCALE,
                        (u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3) * SCALE,
                    )
                )
            draw.line(points, fill="white", width=round(1.6 * SCALE))
            svg.append(f'<path d="M{x0} {y0} C{x1} {y1} {x2} {y2} {x3} {y3}"/>')
    image.resize((128, 128), Image.Resampling.LANCZOS).save(ROOT / f"{name}.png")
    (ROOT / f"{name}.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<g fill="none" stroke="#fff" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round">' + "".join(svg) + "</g></svg>",
        encoding="utf-8",
    )


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    person = [("ellipse", (5, 3, 13, 11)), ("curve", (2, 21, 2, 12, 15, 12, 15, 17))]
    icons = {
        "limit": [
            ("line", (6, 3, 6, 21)),
            ("line", (2, 17, 6, 21, 10, 17)),
            ("line", (18, 21, 18, 3)),
            ("line", (14, 7, 18, 3, 22, 7)),
        ],
        "glaza": [
            ("curve", (2, 12, 7, 3, 17, 3, 22, 12)),
            ("curve", (2, 12, 7, 21, 17, 21, 22, 12)),
            ("ellipse", (8, 8, 16, 16)),
            ("line", (3, 21, 21, 3)),
        ],
        "redact": [
            ("line", (3, 16, 16, 3, 21, 8, 8, 21, 2, 22, 3, 16)),
            ("line", (13, 6, 18, 11)),
            ("line", (3, 16, 8, 21)),
        ],
        "korona": [
            ("line", (3, 17, 2, 6, 8, 10, 12, 3, 16, 10, 22, 6, 21, 17, 3, 17)),
            ("line", (3, 21, 21, 21)),
        ],
        "zapret": person
        + [
            ("line", (2, 21, 11, 21)),
            ("ellipse", (13, 13, 23, 23)),
            ("line", (14.5, 21.5, 21.5, 14.5)),
        ],
        "lock": [
            ("curve", (6, 11, 6, 0, 18, 0, 18, 11)),
            ("line", (4, 11, 20, 11, 20, 22, 4, 22, 4, 11)),
            ("ellipse", (10.5, 14, 13.5, 17)),
            ("line", (12, 17, 12, 19)),
        ],
        "adduser": person
        + [("line", (2, 21, 12, 21)), ("line", (18, 14, 18, 22)), ("line", (14, 18, 22, 18))],
    }
    for name, shapes in icons.items():
        build(name, shapes)
    preview = Image.new("RGB", (7 * 160, 180), "#202124")
    draw = ImageDraw.Draw(preview)
    for index, name in enumerate(icons):
        icon = Image.open(ROOT / f"{name}.png")
        preview.paste(icon, (index * 160 + 16, 10), icon)
        draw.text((index * 160 + 50, 150), name, fill="white")
    preview.save(ROOT / "preview.png")


if __name__ == "__main__":
    main()
