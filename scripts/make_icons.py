"""Draw the app icons: the route line from the train page, a stop, a pass, and the blue train. Run once, commit PNGs."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "src/realliferail/web/static/icons"
PAGE, INK, RAIL, TRAIN = (14, 15, 17), (237, 237, 234), (74, 75, 80), (95, 168, 255)


def draw(size: int, safe: float) -> Image.Image:
    img = Image.new("RGB", (size, size), PAGE)
    d = ImageDraw.Draw(img)
    u = size * safe / 10  # drawing unit inside the safe zone
    cx = size / 2
    top, bottom = size / 2 - 4 * u, size / 2 + 4 * u
    d.rectangle([cx - 0.3 * u, top, cx + 0.3 * u, bottom], fill=RAIL)
    d.rectangle([cx - 0.3 * u, top, cx + 0.3 * u, size / 2 + 0.6 * u], fill=INK)  # the part already travelled
    for y in (top + 0.6 * u, bottom - 0.6 * u):
        d.rectangle(
            [cx - 1.1 * u, y - 1.1 * u, cx + 1.1 * u, y + 1.1 * u], fill=PAGE, outline=INK, width=max(int(0.45 * u), 2)
        )
    d.rectangle([cx - 0.8 * u, size / 2 + 1.6 * u - 0.15 * u, cx + 0.8 * u, size / 2 + 1.6 * u + 0.15 * u], fill=RAIL)
    d.rectangle([cx - 0.9 * u, size / 2 - 1.2 * u, cx + 0.9 * u, size / 2 + 1.2 * u], fill=TRAIN)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, 0.95).save(OUT / "icon-192.png")
    draw(512, 0.95).save(OUT / "icon-512.png")
    draw(512, 0.7).save(OUT / "icon-maskable-512.png")
    print("wrote", sorted(p.name for p in OUT.iterdir()))
