"""Crop status/nav bars off Play screenshots and fit to exactly 1080x1920 (9:16)."""
from PIL import Image
import os, glob, re

SRC = r"C:\Users\msicu\Quran_Teacher_v2\mobile\store"
OUT = os.path.join(SRC, "play")
os.makedirs(OUT, exist_ok=True)
TOP_CROP, BOT_CROP = 75, 140          # status bar / nav bar in the 921x2048 originals
W, H = 1080, 1920

def edge_pad(im, w, h):
    """Centre im on a w x h canvas, filling side gaps by stretching the edge columns."""
    canvas = Image.new("RGB", (w, h))
    x = (w - im.width) // 2
    if x > 0:
        left = im.crop((0, 0, 1, im.height)).resize((x, im.height))
        right = im.crop((im.width - 1, 0, im.width, im.height)).resize((w - x - im.width, im.height))
        canvas.paste(left, (0, 0))
        canvas.paste(right, (x + im.width, 0))
    canvas.paste(im, (x, (h - im.height) // 2))
    return canvas

for src in sorted(glob.glob(os.path.join(SRC, "app-*.jpg")),
                  key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)))):
    im = Image.open(src).convert("RGB")
    im = im.crop((0, TOP_CROP, im.width, im.height - BOT_CROP))
    scale = H / im.height
    im = im.resize((round(im.width * scale), H), Image.LANCZOS)
    if im.width > W:                                   # too wide: centre-crop instead
        off = (im.width - W) // 2
        im = im.crop((off, 0, off + W, H))
    out = edge_pad(im, W, H)
    dst = os.path.join(OUT, os.path.basename(src).replace(".jpg", ".png"))
    out.save(dst)
    print(f"{os.path.basename(src)} -> {os.path.basename(dst)}  {out.size}")
