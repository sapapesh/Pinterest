"""Pin image factory: renders 1000x1500 (2:3) pins with Pillow.

Four layouts per book (hero, benefit, teaser, quote) x `text_versions`
text/color versions. Colors are pulled from each book's own cover so the pins
look like they belong to the book. Image keys look like "hero1", "quote2".
"""
import colorsys
import hashlib
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import PINS, ROOT, SAMPLES, load_config
from .copywriter import make_copy

W, H = 1000, 1500
_cfg = None
_fonts = {}


def cfg():
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


# ---------------------------------------------------------------- fonts / text
def font(kind, size):
    key = (kind, size)
    if key in _fonts:
        return _fonts[key]
    f = None
    for p in cfg()["fonts"][kind]:
        path = ROOT / p if not p.startswith(("/", "C:")) else p
        try:
            f = ImageFont.truetype(str(path), size)
            break
        except OSError:
            continue
    if f is None:
        f = ImageFont.load_default(size)
    _fonts[key] = f
    return f


def text_w(draw, s, f):
    return draw.textlength(s, font=f)


def wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if text_w(draw, t, f) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_block(draw, text, kind, max_w, max_h, start, min_size=34, gap=1.18, max_lines=99):
    """Largest font size where the wrapped text fits the box."""
    size = start
    while size >= min_size:
        f = font(kind, size)
        lines = wrap(draw, text, f, max_w)
        h = len(lines) * size * gap
        if h <= max_h and len(lines) <= max_lines:
            return f, lines, size
        size -= 4
    f = font(kind, min_size)
    return f, wrap(draw, text, f, max_w), min_size


def draw_lines(draw, lines, f, size, cx, y, fill, gap=1.18, shadow=None):
    for ln in lines:
        w = text_w(draw, ln, f)
        if shadow:
            draw.text((cx - w / 2 + 2, y + 3), ln, font=f, fill=shadow)
        draw.text((cx - w / 2, y), ln, font=f, fill=fill)
        y += size * gap
    return y


def tracked(draw, text, f, cx, y, fill, spacing=6):
    total = sum(text_w(draw, c, f) + spacing for c in text) - spacing
    x = cx - total / 2
    for c in text:
        draw.text((x, y), c, font=f, fill=fill)
        x += text_w(draw, c, f) + spacing


# ---------------------------------------------------------------- color
def lum(c):
    r, g, b = [v / 255 for v in c]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def palette(cover):
    small = cover.convert("RGB").resize((72, 72))
    q = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:18]
    cols = [(pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]) for i in range(6)]
    best, best_score = cols[0], -1
    for c in cols:
        h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in c])
        score = s * (1 - abs(v - 0.6))
        if score > best_score:
            best, best_score = c, score
    h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in best])
    accent = hsv(h, min(1.0, max(s, 0.35)), min(0.85, max(v, 0.45)))
    return {
        "accent": accent,
        "dark": mix(accent, (12, 12, 20), 0.62),
        "deeper": mix(accent, (8, 8, 14), 0.78),
        "light": mix(accent, (255, 255, 255), 0.90),
        "paper": mix(accent, (255, 252, 246), 0.94),
        "hue": h,
    }


def contrast(bg):
    return (255, 255, 255) if lum(bg) < 0.55 else (28, 28, 36)


def gradient(top, bottom):
    g = Image.linear_gradient("L").resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), bottom), Image.new("RGB", (W, H), top), g)


# ---------------------------------------------------------------- shapes
def rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r, fill=255)
    return m


def place_cover(canvas, cover, max_w, max_h, cx, top, radius=14, angle=0):
    c = cover.convert("RGB")
    scale = min(max_w / c.width, max_h / c.height)
    c = c.resize((int(c.width * scale), int(c.height * scale)), Image.LANCZOS)
    c.putalpha(rounded_mask(c.size, radius))
    if angle:
        c = c.rotate(angle, expand=True, resample=Image.BICUBIC)
    sh = Image.new("RGBA", (c.width + 120, c.height + 120), (0, 0, 0, 0))
    a = c.split()[3].point(lambda v: int(v * 0.55))
    sh.paste((0, 0, 0, 255), (60, 78), a)
    sh = sh.filter(ImageFilter.GaussianBlur(24))
    x = int(cx - c.width / 2)
    canvas.paste(sh, (x - 60, top - 60), sh)
    canvas.paste(c, (x, top), c)
    return top + c.height


def pill(draw, cx, cy, text, f, bg, fg, pad_x=44, pad_y=22):
    w = text_w(draw, text, f)
    bb = f.getbbox(text)
    h = bb[3] - bb[1]
    box = (cx - w / 2 - pad_x, cy - h / 2 - pad_y, cx + w / 2 + pad_x, cy + h / 2 + pad_y)
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) / 2, fill=bg)
    draw.text((cx - w / 2, cy - h / 2 - bb[1]), text, font=f, fill=fg)
    return box


def check(draw, cx, cy, r, bg, fg):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=bg)
    pts = [(cx - r * .45, cy + r * .02), (cx - r * .1, cy + r * .38), (cx + r * .5, cy - r * .35)]
    draw.line(pts, fill=fg, width=max(4, int(r * .22)), joint="curve")


# ---------------------------------------------------------------- motifs (teaser)
def motif_mandala(size, pal, rng):
    S = size
    img = Image.new("RGB", (S, S), (255, 255, 255))
    d = ImageDraw.Draw(img)
    cx = cy = S / 2
    tints = [mix(pal["accent"], (255, 255, 255), t) for t in (0.35, 0.55, 0.75)]
    tints += [hsv(pal["hue"] + o, 0.35, 0.95) for o in (0.1, 0.5, 0.62)]
    rings = [(0.08, 0.24, 8), (0.24, 0.42, 12), (0.42, 0.60, 16), (0.60, 0.78, 20), (0.78, 0.96, 24)]
    for ri, (r0, r1, k) in enumerate(rings):
        mid_r = (r0 + r1) / 2 * S / 2
        width = min((r1 - r0) * S / 2 * 0.80, math.pi * mid_r / k * 0.98)
        for i in range(k):
            ang = 2 * math.pi * i / k + (math.pi / k if ri % 2 else 0)
            pts_l, pts_r = [], []
            for t in [j / 16 for j in range(17)]:
                rad = (r0 + (r1 - r0) * 1.22 * t) * S / 2
                hw = width * (math.sin(math.pi * t) ** 0.85)
                px, py = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
                nx, ny = -math.sin(ang), math.cos(ang)
                pts_l.append((px + nx * hw, py + ny * hw))
                pts_r.append((px - nx * hw, py - ny * hw))
            poly = pts_l + pts_r[::-1]
            fill = rng.choice(tints) if rng.random() < 0.38 else None
            d.polygon(poly, fill=fill, outline=(30, 30, 40))
            d.line(poly + [poly[0]], fill=(30, 30, 40), width=3)
            mid = (r0 + (r1 - r0) * .55) * S / 2
            dx, dy = cx + mid * math.cos(ang), cy + mid * math.sin(ang)
            d.ellipse((dx - 5, dy - 5, dx + 5, dy + 5), outline=(30, 30, 40), width=2)
    for rr in (0.04, 0.07):
        d.ellipse((cx - rr * S, cy - rr * S, cx + rr * S, cy + rr * S), outline=(30, 30, 40), width=3)
    return img


def motif_logic(size, pal, rng):
    n = 7
    S = size
    cell = S / n
    img = Image.new("RGB", (S, S), (255, 255, 255))
    d = ImageDraw.Draw(img)
    region = [[-1] * n for _ in range(n)]
    seeds = rng.sample([(r, c) for r in range(n) for c in range(n)], n)
    frontier = []
    for i, (r, c) in enumerate(seeds):
        region[r][c] = i
        frontier.append((r, c))
    while frontier:
        r, c = frontier.pop(rng.randrange(len(frontier)))
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < n and region[nr][nc] == -1:
                region[nr][nc] = region[r][c]
                frontier.append((nr, nc))
                frontier.append((r, c))
                break
    cols = [hsv(pal["hue"] + i / n, 0.38, 0.97) for i in range(n)]
    for r in range(n):
        for c in range(n):
            d.rectangle((c * cell, r * cell, (c + 1) * cell, (r + 1) * cell), fill=cols[region[r][c]])
    for r in range(n + 1):
        d.line((0, r * cell, S, r * cell), fill=(120, 120, 130), width=2)
        d.line((r * cell, 0, r * cell, S), fill=(120, 120, 130), width=2)
    for r in range(n):
        for c in range(n):
            if c + 1 < n and region[r][c] != region[r][c + 1]:
                d.line(((c + 1) * cell, r * cell, (c + 1) * cell, (r + 1) * cell), fill=(20, 20, 30), width=7)
            if r + 1 < n and region[r][c] != region[r + 1][c]:
                d.line((c * cell, (r + 1) * cell, (c + 1) * cell, (r + 1) * cell), fill=(20, 20, 30), width=7)
    d.rectangle((0, 0, S - 1, S - 1), outline=(20, 20, 30), width=7)
    perm = list(range(n))
    rng.shuffle(perm)
    for r in range(n):
        if rng.random() < 0.6:
            c = perm[r]
            cx, cy = (c + .5) * cell, (r + .5) * cell
            d.ellipse((cx - cell * .24, cy - cell * .24, cx + cell * .24, cy + cell * .24), fill=(20, 20, 30))
    return img


def motif_sudoku(size, pal, rng):
    S = size
    cell = S / 9
    img = Image.new("RGB", (S, S), (255, 255, 255))
    d = ImageDraw.Draw(img)
    digits = list(range(1, 10))
    rng.shuffle(digits)
    f = font("sans", int(cell * 0.62))
    for r in range(9):
        for c in range(9):
            if rng.random() < 0.42:
                v = digits[(r * 3 + r // 3 + c) % 9]
                s = str(v)
                bb = f.getbbox(s)
                d.text(((c + .5) * cell - (bb[2] - bb[0]) / 2 - bb[0], (r + .5) * cell - (bb[3] - bb[1]) / 2 - bb[1]),
                       s, font=f, fill=(25, 25, 35))
    for i in range(10):
        w = 6 if i % 3 == 0 else 2
        d.line((0, i * cell, S, i * cell), fill=(25, 25, 35), width=w)
        d.line((i * cell, 0, i * cell, S), fill=(25, 25, 35), width=w)
    return img


def motif_journal(size, pal, rng):
    S = size
    img = Image.new("RGB", (S, S), (255, 253, 248))
    d = ImageDraw.Draw(img)
    f = font("sans", 34)
    d.text((40, 34), "Today's check-in", font=font("serif", 44), fill=pal["deeper"])
    y = 130
    labels = ["Morning routine", "Medications", "Meals & fluids", "Appointments", "Notes for tomorrow"]
    for lab in labels:
        d.rounded_rectangle((40, y, 40 + 34, y + 34), 6, outline=pal["accent"], width=4)
        d.text((100, y - 2), lab, font=f, fill=(60, 60, 70))
        d.line((100, y + 56, S - 40, y + 56), fill=(205, 205, 210), width=2)
        y += 88
    d.text((40, y + 10), "How am I feeling?", font=f, fill=(60, 60, 70))
    for i in range(5):
        cx = 440 + i * 66
        d.ellipse((cx - 24, y + 4, cx + 24, y + 52), outline=pal["accent"], width=4)
    for k in range(3):
        d.line((40, y + 110 + k * 52, S - 40, y + 110 + k * 52), fill=(205, 205, 210), width=2)
    return img


def motif_wordsearch(size, pal, rng):
    n = 10
    S = size
    cell = S / n
    img = Image.new("RGB", (S, S), (255, 255, 255))
    d = ImageDraw.Draw(img)
    letters = [[rng.choice("ABCDEFGHIKLMNOPRSTUWY") for _ in range(n)] for _ in range(n)]
    word = "PUZZLE"
    r0, c0 = rng.randrange(2, 8), rng.randrange(0, n - len(word) + 1)
    for i, ch in enumerate(word):
        letters[r0][c0 + i] = ch
    d.rounded_rectangle((c0 * cell + 4, r0 * cell + 6, (c0 + len(word)) * cell - 4, (r0 + 1) * cell - 6),
                        radius=cell / 2 - 6, fill=mix(pal["accent"], (255, 255, 255), 0.6))
    f = font("sans", int(cell * 0.56))
    for r in range(n):
        for c in range(n):
            s = letters[r][c]
            bb = f.getbbox(s)
            d.text(((c + .5) * cell - (bb[2] - bb[0]) / 2 - bb[0], (r + .5) * cell - (bb[3] - bb[1]) / 2 - bb[1]),
                   s, font=f, fill=(25, 25, 35))
    d.rectangle((0, 0, S - 1, S - 1), outline=(25, 25, 35), width=5)
    return img


MOTIFS = {"mandala": motif_mandala, "logic": motif_logic, "mystery": motif_sudoku,
          "journal": motif_journal, "wordsearch": motif_wordsearch}


def teaser_art(book, pal, size):
    """Use the author's own sample page if one exists, otherwise draw a motif."""
    folder = SAMPLES / book.id
    if folder.is_dir():
        imgs = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        if imgs:
            im = Image.open(imgs[0]).convert("RGB")
            im = ImageOps.contain(im, (size, size), Image.LANCZOS)
            return im
    rng = random.Random(int(hashlib.md5(book.id.encode()).hexdigest(), 16) % 10**8)
    return MOTIFS.get(book.category, motif_logic)(size, pal, rng)


# ---------------------------------------------------------------- layouts
def scheme(pal, version):
    if version % 2 == 1:
        top, bot = pal["dark"], mix(pal["accent"], pal["dark"], 0.35)
    else:
        top, bot = pal["deeper"], pal["dark"]
    return top, bot, contrast(top)


def v_hero(book, cover, pal, cp, version):
    top, bot, fg = scheme(pal, version)
    img = gradient(top, bot)
    d = ImageDraw.Draw(img)
    tracked(d, cp["kicker"], font("sans", 30), W / 2, 70, mix(fg, pal["accent"], 0.0) if version % 2 else fg, 7)
    f, lines, size = fit_block(d, book.title, "serif", 860, 250, 100, 52, max_lines=3)
    y = draw_lines(d, lines, f, size, W / 2, 130, fg, shadow=(0, 0, 0))
    if book.subtitle:
        fs, sl, ss = fit_block(d, book.subtitle, "sans_regular", 840, 90, 40, 28, max_lines=2)
        y = draw_lines(d, sl, fs, ss, W / 2, y + 6, mix(fg, top, 0.2))
    bottom = place_cover(img, cover, 640 if version % 2 else 600, 1330 - int(y) - 150,
                         W // 2, int(y) + 40, angle=0 if version % 2 else -4)
    pill(d, W / 2, 1405, cp["cta"], font("sans", 44), pal["light"], pal["deeper"])
    return img


def v_benefit(book, cover, pal, cp, version):
    bg = pal["paper"] if version % 2 == 1 else pal["light"]
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 26), fill=pal["accent"])
    f, lines, size = fit_block(d, cp["headline"], "serif", 840, 400, 98, 58, max_lines=5)
    y = draw_lines(d, lines, f, size, W / 2, 90, pal["deeper"])
    d.line((W / 2 - 80, y + 14, W / 2 + 80, y + 14), fill=pal["accent"], width=7)
    y += 56
    fb = font("sans", 44)
    for b in cp["bullets"]:
        check(d, 120, y + 30, 28, pal["accent"], (255, 255, 255))
        bl = wrap(d, b, fb, 740)
        for ln in bl:
            d.text((175, y + 4), ln, font=fb, fill=(40, 40, 52))
            y += 54
        y += 24
    avail = 1335 - int(y) - 40
    place_cover(img, cover, 520, max(avail, 300), W // 2, int(y) + 20)
    pill(d, W / 2, 1420, cp["cta"], font("sans", 42), pal["deeper"], (255, 255, 255), 40, 20)
    return img


def v_teaser(book, cover, pal, cp, version):
    top, bot, fg = scheme(pal, version + 1)
    img = gradient(top, bot)
    d = ImageDraw.Draw(img)
    f, lines, size = fit_block(d, cp["teaser_head"], "serif", 840, 210, 92, 54, max_lines=2)
    y = draw_lines(d, lines, f, size, W / 2, 85, fg, shadow=(0, 0, 0))
    art = teaser_art(book, pal, 640)
    card_w, card_h = art.width + 44, art.height + 44
    card = Image.new("RGB", (card_w, card_h), (255, 255, 255))
    card.paste(art, (22, 22))
    card = card.convert("RGBA")
    card.putalpha(rounded_mask(card.size, 10))
    card = card.rotate(-2.5 if version % 2 else 2.5, expand=True, resample=Image.BICUBIC)
    sh = Image.new("RGBA", (card.width + 120, card.height + 120), (0, 0, 0, 0))
    sh.paste((0, 0, 0, 255), (60, 78), card.split()[3].point(lambda v: int(v * 0.55)))
    sh = sh.filter(ImageFilter.GaussianBlur(22))
    cx = W // 2
    ty = int(y) + 40
    img.paste(sh, (cx - card.width // 2 - 60, ty - 60), sh)
    img.paste(card, (cx - card.width // 2, ty), card)
    by = ty + card.height + 50
    place_cover(img, cover, 250, 1440 - by, 190, by)
    d = ImageDraw.Draw(img)
    fs, tl, ts = fit_block(d, book.title, "serif", 520, 190, 48, 30, max_lines=3)
    ty2 = by + 10
    for ln in tl:
        d.text((350, ty2), ln, font=fs, fill=fg)
        ty2 += ts * 1.2
    pill(d, 610, ty2 + 62, cp["cta"], font("sans", 32), pal["light"], pal["deeper"], 30, 16)
    return img


def v_quote(book, cover, pal, cp, version):
    bg_top = pal["accent"] if version % 2 == 1 else mix(pal["accent"], pal["dark"], 0.35)
    bg_bot = mix(bg_top, (0, 0, 0), 0.30)
    fg = contrast(mix(bg_top, bg_bot, .5))
    img = gradient(bg_top, bg_bot)
    d = ImageDraw.Draw(img)
    d.text((70, 20), "“", font=font("serif", 340), fill=mix(fg, bg_top, 0.65))
    f, lines, size = fit_block(d, cp["quote"], "serif", 800, 520, 104, 56, max_lines=6)
    y = draw_lines(d, lines, f, size, W / 2, 330, fg, shadow=(0, 0, 0) if lum(bg_top) < .55 else None)
    d.line((W / 2 - 70, y + 20, W / 2 + 70, y + 20), fill=fg, width=6)
    avail = 1330 - int(y) - 60
    bottom = place_cover(img, cover, 430, max(avail, 280), W // 2, int(y) + 60)
    d = ImageDraw.Draw(img)
    f2, l2, s2 = fit_block(d, book.title, "sans", 860, 70, 40, 28, max_lines=1)
    draw_lines(d, l2, f2, s2, W / 2, bottom + 34, fg)
    return img


LAYOUTS = {"hero": v_hero, "benefit": v_benefit, "teaser": v_teaser, "quote": v_quote}


# ---------------------------------------------------------------- public API
def has_sample(book):
    folder = SAMPLES / book.id
    return folder.is_dir() and any(p.suffix.lower() in (".png", ".jpg", ".jpeg") for p in folder.iterdir())


def all_keys():
    c = cfg()
    return [f"{v}{n}" for n in range(1, c["text_versions"] + 1) for v in c["variants"]]


def image_keys(book=None):
    """Image keys usable for a book. Categories listed in `teaser_needs_sample`
    only get the 'teaser' layout when you've put a real sample page in
    samples/<book id>/, because a drawn stand-in could misrepresent the pages."""
    keys = all_keys()
    if book is not None and not has_sample(book) and book.category in cfg().get("teaser_needs_sample", []):
        keys = [k for k in keys if not k.startswith("teaser")]
    return keys


def split_key(key):
    return key.rstrip("0123456789"), int(key[len(key.rstrip("0123456789")):])


def image_path(book, key):
    return PINS / book.id / f"{key}.jpg"


def copy_for(book, key):
    variant, version = split_key(key)
    return make_copy(book, variant, version, all_keys().index(key), has_sample(book))


def render(book, key):
    variant, version = split_key(key)
    cover = Image.open(book.cover_path)
    cover = ImageOps.exif_transpose(cover).convert("RGB")
    pal = palette(cover)
    cp = copy_for(book, key)
    img = LAYOUTS[variant](book, cover, pal, cp, version)
    out = image_path(book, key)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=90, optimize=True)
    return out


def _sig(book):
    """Fingerprint of everything baked into an image, so edits trigger a rebuild."""
    sample_dir = SAMPLES / book.id
    samples = sorted(p.name for p in sample_dir.iterdir()) if sample_dir.is_dir() else []
    s = "|".join([book.title, book.subtitle, book.category, book.cover_file,
                  str(book.cover_path.stat().st_mtime_ns), ",".join(samples)])
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _needs(book, key, force):
    p = image_path(book, key)
    sf = p.with_suffix(".sig")
    return force or not p.exists() or not sf.exists() or sf.read_text() != _sig(book)


def ensure_image(book, key, force=False):
    p = image_path(book, key)
    if _needs(book, key, force):
        render(book, key)
        p.with_suffix(".sig").write_text(_sig(book))
    return p


def build_book(book, force=False):
    n = 0
    for key in image_keys(book):
        if _needs(book, key, force):
            ensure_image(book, key, force=True)
            n += 1
    return n
