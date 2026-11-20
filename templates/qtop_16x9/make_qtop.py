#!/usr/bin/env python3
"""GP edu 16:9 "Question-on-top" template.

Turns a vertical GP edu reel (1080x1920) into a 1920x1080 website video where
the question + options stay pinned at the top for the whole video and the
solution (content card, step label, caption, progress bar) plays below.

Usage:  python3 make_qtop.py config.json
Config keys:
  video        path of the vertical reel
  out          output mp4 path
  qno          e.g. "Q.3/57"
  question     question text  (use ^{..} for superscript, _{..} for subscript)
  options      list of 4 option strings (A..D)
  answer       correct letter, e.g. "A"
  answer_at    seconds when FINAL ANSWER step starts (option turns green)
  endcard_at   seconds when the reel's end card starts (16:9 end card shown)
  intro_until  seconds when STEP 02 starts; before that the left card shows a
               "read the question" panel instead of a duplicate question
  topic        small label on the end card (optional)
"""
import json, os, re, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1920, 1080
S = 0.9                  # reel -> page scale (reel grid 60px -> page grid 54px)
G = int(60 * S)
BG = (239, 239, 229); GRID = (229, 229, 218)
NAVY = (27, 33, 64); OR = (240, 106, 34); GREY = (105, 105, 105)
GREEN = (34, 160, 90); GREEN_BG = (226, 246, 233); LINE = (215, 215, 205)
FD = '/usr/share/fonts/opentype/inter/'
def F(w, s): return ImageFont.truetype(f'{FD}Inter-{w}.otf', s)

# ---- reel crops (reel coords, multiples of 60 so grids line up) -> page pos
# page pos must satisfy p = S*src + k*G so the reel grid lines up with the page grid
CONTENT = dict(src=(40, 240, 1000, 900), dst=(36, 270))     # card area
LABEL   = dict(src=(30, 148, 1020, 92),  dst=(999, 349))    # STEP label row
CAPTION = dict(src=(30, 1140, 1020, 180), dst=(999, 486))   # big caption
PROG    = dict(src=(30, 1320, 1030, 240), dst=(999, 702))   # S1..S8 bar + cgpedu.com
TOP_H = 270

def grid_bg():
    im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)
    for x in range(0, W, G): d.line([(x - 1, 0), (x - 1, H)], fill=GRID, width=2)
    for y in range(0, H, G): d.line([(0, y - 1), (W, y - 1)], fill=GRID, width=2)
    return im

# ---- rich text with ^{sup} and _{sub}
TOK = re.compile(r'(\^\{[^}]*\}|_\{[^}]*\})')
def runs(t):
    out = []
    for p in TOK.split(t):
        if not p: continue
        if p.startswith('^{'): out.append((p[2:-1], 'sup'))
        elif p.startswith('_{'): out.append((p[2:-1], 'sub'))
        else: out.append((p, 'n'))
    return out
def rich_w(d, t, f, fs):
    return sum(d.textlength(s, font=(fs if k != 'n' else f)) for s, k in runs(t))
def rich(d, x, y, t, f, fs, col):
    sz = f.size
    for s, k in runs(t):
        ff = fs if k != 'n' else f
        dy = -int(sz * 0.18) if k == 'sup' else (int(sz * 0.45) if k == 'sub' else 0)
        d.text((x, y + dy), s, font=ff, fill=col); x += d.textlength(s, font=ff)
    return x
def wrap(d, t, f, fs, maxw):
    lines, cur = [], ''
    for w in t.split(' '):
        tr = (cur + ' ' + w).strip()
        if rich_w(d, tr, f, fs) <= maxw: cur = tr
        else: lines.append(cur); cur = w
    lines.append(cur); return lines

def key_logo(frame_png):
    e = np.asarray(Image.open(frame_png).convert('RGB')).astype(float)
    crop = e[480:1010, 270:820]
    B = np.median(e[400:440, 100:200].reshape(-1, 3), axis=0)
    a = np.clip(((B - crop) / B).max(axis=2) * 1.25, 0, 1); a[a < 0.06] = 0
    C = np.clip((crop - (1 - a[..., None]) * B) / np.maximum(a[..., None], 1e-3), 0, 255)
    lg = Image.fromarray(np.dstack([C, a * 255]).astype('uint8'), 'RGBA')
    return lg.crop(lg.getbbox())

def top_card(cfg, logo, answered):
    im = Image.new('RGBA', (W, TOP_H), (0, 0, 0, 0))
    sh = Image.new('L', (W, TOP_H), 0)
    ImageDraw.Draw(sh).rounded_rectangle([40, 18, W - 40, TOP_H - 4], 26, fill=70)
    sh = sh.filter(ImageFilter.GaussianBlur(12))
    im.paste((150, 150, 140, 255), (0, 0), sh)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([30, 10, W - 30, TOP_H - 12], 26, fill=(255, 255, 255, 255))
    # header row: pill + label + small logo
    pf = F('Bold', 22); pw = d.textlength(cfg['qno'], font=pf)
    d.rounded_rectangle([66, 24, 66 + pw + 32, 58], 17, fill=(240, 240, 232))
    d.text((82, 28), cfg['qno'], font=pf, fill=NAVY)
    d.text((66 + pw + 52, 30), "TODAY'S QUESTION", font=F('Bold', 20), fill=GREY)
    lg = logo.copy(); lg.thumbnail((80, 46), Image.LANCZOS)
    im.alpha_composite(lg, (W - 66 - lg.width, 18))
    # question text (auto-fit to 3 lines)
    maxw = W - 132
    for size in (32, 30, 29, 28, 26):
        f, fs = F('SemiBold', size), F('SemiBold', int(size * 0.62))
        lines = wrap(d, cfg['question'], f, fs, maxw)
        if len(lines) <= 3: break
    lh = int(size * 1.3); y = 66 + (3 - len(lines)) * lh // 2
    for ln in lines: rich(d, 66, y, ln, f, fs, NAVY); y += lh
    # options row
    n = len(cfg['options']); gap = 24; ow = (maxw - gap * (n - 1)) / n
    oy0, oy1 = 194, 246
    of, ofs = F('SemiBold', 26), F('SemiBold', 17)
    for i, o in enumerate(cfg['options']):
        L = 'ABCD'[i]; x0 = 66 + i * (ow + gap); x1 = x0 + ow
        right = answered and L == cfg['answer']
        d.rounded_rectangle([x0, oy0, x1, oy1], 14, fill=GREEN_BG if right else (255, 255, 255),
                            outline=GREEN if right else LINE, width=3)
        cy = (oy0 + oy1) // 2
        if right:
            d.ellipse([x0 + 18, cy - 15, x0 + 48, cy + 15], fill=GREEN)
            d.line([(x0 + 25, cy), (x0 + 31, cy + 7), (x0 + 42, cy - 7)], fill='white', width=4)
        else:
            d.ellipse([x0 + 18, cy - 15, x0 + 48, cy + 15], outline=NAVY, width=3)
        col = GREEN if right else NAVY
        tx = x0 + 62; d.text((tx, cy - 16), f'{L}.', font=F('ExtraBold', 26), fill=col)
        rich(d, tx + 38, cy - 16, o, of, ofs, col)
    return im

def intro_card():
    sx, sy = CONTENT['src'][:2]; dx, dy = CONTENT['dst']
    x0 = dx + (70 - sx) * S; x1 = dx + (1010 - sx) * S
    y0 = dy + (290 - sy) * S - 40; y1 = dy + (1085 - sy) * S + 50
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sh = Image.new('L', (W, H), 0)
    ImageDraw.Draw(sh).rounded_rectangle([x0 + 8, y0 + 50, x1 - 8, y1 - 40], 30, fill=60)
    im.paste((150, 150, 140, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0 + 40, x1, y1 - 50], 30, fill=(255, 255, 255, 255))
    cx = (x0 + x1) / 2
    # up arrow
    d.polygon([(cx, y0 + 110), (cx - 45, y0 + 165), (cx + 45, y0 + 165)], fill=OR)
    d.rectangle([cx - 16, y0 + 160, cx + 16, y0 + 215], fill=OR)
    def ct(t, y, f, c):
        d.text((cx - d.textlength(t, font=f) / 2, y), t, font=f, fill=c)
    ct('Read the question', y0 + 260, F('ExtraBold', 60), NAVY)
    ct('carefully', y0 + 335, F('ExtraBold', 60), OR)
    d.line([(cx - 50, y0 + 440), (cx + 50, y0 + 440)], fill=OR, width=4)
    ct('It stays on top till the end —', y0 + 475, F('SemiBold', 32), GREY)
    ct('solution starts in the next step', y0 + 522, F('SemiBold', 32), GREY)
    return im

def end_card(cfg, logo):
    im = Image.new('RGB', (W, H), (246, 245, 240)); d = ImageDraw.Draw(im)
    v = Image.new('L', (W, H), 0)
    ImageDraw.Draw(v).ellipse([W/2 - 900, H/2 - 650, W/2 + 900, H/2 + 650], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(160))
    im = Image.composite(Image.new('RGB', (W, H), (252, 251, 248)), im, v); d = ImageDraw.Draw(im)
    lg = logo.copy(); lg.thumbnail((420, 330), Image.LANCZOS)
    im.paste(lg, ((W - lg.width) // 2, 180), lg)
    def ct(t, y, f, c):
        d.text(((W - d.textlength(t, font=f)) / 2, y), t, font=f, fill=c)
    ct('P R A C T I C E   T O D A Y ,   A C H I E V E   T O M O R R O W', 600, F('Bold', 34), NAVY)
    d.line([(W/2 - 60, 680), (W/2 + 60, 680)], fill=OR, width=4)
    ct('cgpedu.com', 715, F('Bold', 48), NAVY)
    return im

def main(cfgp):
    cfg = json.load(open(cfgp)); tmp = tempfile.mkdtemp()
    v = cfg['video']; endt = cfg['endcard_at']
    dur = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
          'format=duration', '-of', 'csv=p=0', v]).decode())
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(dur - 0.5), '-i', v,
                    '-frames:v', '1', f'{tmp}/end.png'], check=True)
    logo = key_logo(f'{tmp}/end.png')
    grid_bg().save(f'{tmp}/bg.png')
    top_card(cfg, logo, False).save(f'{tmp}/top0.png')
    top_card(cfg, logo, True).save(f'{tmp}/top1.png')
    end_card(cfg, logo).save(f'{tmp}/endcard.png')
    intro_card().save(f'{tmp}/intro.png')
    def crop(c, name):
        x, y, w, h = c['src']
        return f"[1:v]crop={w}:{h}:{x}:{y},scale={round(w*S)}:{round(h*S)}:flags=lanczos[{name}]"
    parts = ["[1:v]split=4[s1][s2][s3][s4]"]
    for i, (c, n) in enumerate([(CONTENT, 'c'), (LABEL, 'l'), (CAPTION, 'k'), (PROG, 'p')]):
        parts.append(crop(c, n).replace('[1:v]', f'[s{i+1}]'))
    a = cfg['answer_at']
    parts += [
        "[0:v][c]overlay=%d:%d[o0]" % CONTENT['dst'],
        f"[o0][5:v]overlay=0:0:enable='lt(t,{cfg.get('intro_until', 0)})'[o1]",
        "[o1][l]overlay=%d:%d[o2]" % LABEL['dst'],
        "[o2][k]overlay=%d:%d[o3]" % CAPTION['dst'],
        "[o3][p]overlay=%d:%d[o4]" % PROG['dst'],
        f"[o4][2:v]overlay=0:0:enable='lt(t,{a})'[o5]",
        f"[o5][3:v]overlay=0:0:enable='gte(t,{a})'[o6]",
        f"[4:v]format=rgba,fade=t=in:st={endt}:d=0.4:alpha=1[ec]",
        f"[o6][ec]overlay=0:0:enable='gte(t,{endt})',format=yuv420p[out]",
    ]
    cmd = ['ffmpeg', '-v', 'error', '-y',
           '-loop', '1', '-framerate', '30', '-i', f'{tmp}/bg.png', '-i', v,
           '-loop', '1', '-framerate', '30', '-i', f'{tmp}/top0.png',
           '-loop', '1', '-framerate', '30', '-i', f'{tmp}/top1.png',
           '-loop', '1', '-framerate', '30', '-i', f'{tmp}/endcard.png',
           '-loop', '1', '-framerate', '30', '-i', f'{tmp}/intro.png',
           '-filter_complex', ';'.join(parts), '-map', '[out]', '-map', '1:a',
           '-t', str(dur), '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-r', '30',
           '-c:a', 'copy', '-movflags', '+faststart', cfg['out']]
    subprocess.run(cmd, check=True); print('done ->', cfg['out'])

if __name__ == '__main__':
    main(sys.argv[1])
