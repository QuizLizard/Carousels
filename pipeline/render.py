#!/usr/bin/env python3
"""Quiz Lizard carousel renderer. Outputs 9 slides x 2 aspect ratios from a JSON spec."""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

UP   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Nunito.ttf")
EMOJI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoColorEmoji.ttf")

CARD      = (242, 241, 240)
CARD_OK   = (222, 238, 195)
SHADOW    = (0, 0, 0, 176)
INK       = (26, 26, 26)
GREEN     = (128, 182, 42)
RADIUS    = 30
SH_DX, SH_DY = 19, 16

HEADERS = {
    ("q", 1): "TikTok_Carousel_Template.png",
    ("a", 1): "TikTok_Carousel_Template__1_.png",
    ("q", 2): "TikTok_Carousel_Template__2_.png",
    ("a", 2): "TikTok_Carousel_Template__3_.png",
    ("q", 3): "TikTok_Carousel_Template__4_.png",
    ("a", 3): "TikTok_Carousel_Template__5_.png",
    ("q", 4): "TikTok_Carousel_Template__6_.png",
    ("a", 4): "TikTok_Carousel_Template__7_.png",
    ("score", 0): "TikTok_Carousel_Template__8_.png",
}
CTA = "TikTok_Carousel_Template__9_.png"

# Content block is 832 wide (two 400 cards + 32 gap), centred on a 1080 canvas.
BLOCK_W, CARD_W, GAP, CARD_H, Q_H = 832, 400, 32, 151, 207
LEFT = (1080 - BLOCK_W) // 2

LAYOUTS = {
    "4x5": dict(size=(1080, 1350), header_cy=248, q_top=415,
                row1=675, row2=879, footer_cy=1107, hdr_max=(760, 190),
                sc_top=400, sc_cta=985),
    "9x16": dict(size=(1080, 1920), header_cy=360, q_top=560,
                 row1=870, row2=1074, footer_cy=1290, hdr_max=(820, 205),
                 sc_top=560, sc_cta=1170),
}


def font(size, weight="SemiBold"):
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_name(weight)
    return f


def background(size):
    bg = Image.open(os.path.join(UP, "Background_story.png")).convert("RGB")
    tw, th = size
    scale = max(tw / bg.width, th / bg.height)
    bg = bg.resize((round(bg.width * scale), round(bg.height * scale)), Image.LANCZOS)
    x, y = (bg.width - tw) // 2, (bg.height - th) // 2
    return bg.crop((x, y, x + tw, y + th)).convert("RGBA")


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, max_w, max_h, start, weight="SemiBold", floor=18):
    """Shrink until the wrapped block fits the box."""
    size = start
    while size >= floor:
        fnt = font(size, weight)
        lines = wrap(draw, text, fnt, max_w)
        lh = round(size * 1.32)
        if len(lines) * lh <= max_h:
            return fnt, lines, lh
        size -= 1
    fnt = font(floor, weight)
    return fnt, wrap(draw, text, fnt, max_w), round(floor * 1.32)


def block(draw, lines, lh, fnt, cx, cy, fill=INK):
    top = cy - (len(lines) * lh) / 2
    for i, ln in enumerate(lines):
        w = draw.textlength(ln, font=fnt)
        draw.text((cx - w / 2, top + i * lh + (lh - fnt.size) / 2 - fnt.size * 0.12),
                  ln, font=fnt, fill=fill)


_ecache = {}


def emoji_img(ch, px):
    """NotoColorEmoji is a bitmap font fixed at 109px; render then downscale."""
    key = (ch, px)
    if key in _ecache:
        return _ecache[key]
    f = ImageFont.truetype(EMOJI, 109)
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((20, 20), ch, font=f, embedded_color=True)
    im = im.crop(im.getbbox())
    s = px / im.height
    im = im.resize((max(1, round(im.width * s)), px), Image.LANCZOS)
    _ecache[key] = im
    return im


def tick_badge(base, cx, cy, r=25):
    """Nunito has no U+2713, so the tick is drawn as a vector badge."""
    d = ImageDraw.Draw(base)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GREEN, outline=INK, width=4)
    p = [(cx - r * 0.42, cy + r * 0.02), (cx - r * 0.10, cy + r * 0.36), (cx + r * 0.46, cy - r * 0.34)]
    d.line(p, fill=(255, 255, 255), width=max(4, round(r * 0.30)), joint="curve")


def card(base, box, fill):
    """Rounded card with the template's offset drop shadow."""
    x0, y0, x1, y1 = box
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle(
        (x0 + SH_DX, y0 + SH_DY, x1 + SH_DX - 3, y1 + SH_DY), RADIUS, fill=SHADOW)
    base.alpha_composite(ov)
    ImageDraw.Draw(base).rounded_rectangle(box, RADIUS, fill=fill)


def paste_centred(base, path, cy, max_wh):
    im = Image.open(os.path.join(UP, path)).convert("RGBA")
    mw, mh = max_wh
    s = min(mw / im.width, mh / im.height, 1.0)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    base.alpha_composite(im, ((base.width - im.width) // 2, round(cy - im.height / 2)))


def slide(kind, idx, q, fmt):
    L = LAYOUTS[fmt]
    base = background(L["size"])
    d = ImageDraw.Draw(base)

    paste_centred(base, HEADERS[(kind, idx)], L["header_cy"], L["hdr_max"])

    card(base, (LEFT, L["q_top"], LEFT + BLOCK_W, L["q_top"] + Q_H), CARD)
    fnt, lines, lh = fit(d, q["question"], BLOCK_W - 70, Q_H - 40, 46, "Bold")
    block(d, lines, lh, fnt, 540, L["q_top"] + Q_H / 2)

    show_pct = kind == "a"
    for i, opt in enumerate(q["options"]):
        col, row = i % 2, i // 2
        x = LEFT + col * (CARD_W + GAP)
        y = L["row1"] if row == 0 else L["row2"]
        fill = CARD_OK if (show_pct and opt.get("correct")) else CARD
        card(base, (x, y, x + CARD_W, y + CARD_H), fill)
        txt = f"{opt['letter']}) {opt['text']}"
        if show_pct:
            txt += f" \u2014 {opt['pct']}%"
        avail = CARD_W - 44 - (34 if (show_pct and opt.get("correct")) else 0)
        fnt, lines, lh = fit(d, txt, avail, CARD_H - 26, 34)
        block(d, lines, lh, fnt, x + CARD_W / 2 - (17 if (show_pct and opt.get("correct")) else 0),
              y + CARD_H / 2)
        if show_pct and opt.get("correct"):
            tick_badge(base, x + CARD_W - 38, y + 36)

    footer = q["closing"] if kind == "a" else "Swipe for the answer"
    fnt, lines, lh = fit(d, footer, 700, 110, 40, "Bold")
    block(d, lines, lh, fnt, 540, L["footer_cy"])
    return base.convert("RGB")


def score_slide(fmt, bands):
    L = LAYOUTS[fmt]
    base = background(L["size"])
    d = ImageDraw.Draw(base)
    paste_centred(base, HEADERS[("score", 0)], L["header_cy"] + 20, (620, 300))

    fnt = font(50, "Bold")
    lh, epx, gap = 84, 54, 18
    top = L["sc_top"]
    card_h = len(bands) * lh + 56
    card(base, (LEFT, top, LEFT + BLOCK_W, top + card_h), CARD)

    for i, (label, ch) in enumerate(bands):
        em = emoji_img(ch, epx) if ch else None
        tw = d.textlength(label, font=fnt)
        total = tw + (gap + em.width if em else 0)
        x = 540 - total / 2
        cy = top + 28 + i * lh + lh / 2
        d.text((x, cy - fnt.size * 0.66), label, font=fnt, fill=INK)
        if em:
            base.alpha_composite(em, (round(x + tw + gap), round(cy - em.height / 2)))

    fnt2 = font(44, "ExtraBold")
    msg = "Drop your score in the comments!"
    w = d.textlength(msg, font=fnt2)
    y = top + card_h + 46
    d.text((540 - w / 2, y), msg, font=fnt2, fill=INK)
    d.line((540 - w / 2, y + fnt2.size + 10, 540 + w / 2, y + fnt2.size + 10), fill=INK, width=4)

    paste_centred(base, CTA, L["sc_cta"], (740, 270))
    return base.convert("RGB")


def render(spec_path, outdir):
    spec = json.load(open(spec_path))
    os.makedirs(outdir, exist_ok=True)
    made = []
    for fmt in ("4x5", "9x16"):
        n = 1
        for i, q in enumerate(spec["questions"], start=1):
            for kind in ("q", "a"):
                img = slide(kind, i, q, fmt)
                p = os.path.join(outdir, f"{spec['slug']}_{fmt}_{n:02d}.jpg")
                img.save(p, "JPEG", quality=92, optimize=True)
                made.append(p)
                n += 1
        img = score_slide(fmt, spec["score_bands"])
        p = os.path.join(outdir, f"{spec['slug']}_{fmt}_{n:02d}.jpg")
        img.save(p, "JPEG", quality=92, optimize=True)
        made.append(p)
    return made


if __name__ == "__main__":
    for p in render(sys.argv[1], sys.argv[2]):
        print(p)
