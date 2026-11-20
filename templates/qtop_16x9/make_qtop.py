#!/usr/bin/env python3
"""GP edu 16:9 "Question-on-top" template (v2).

Takes a vertical GP edu reel (1080x1920) and makes a 1920x1080 website video:
  * question + options pinned on top for the whole video (key values get
    highlighted while the question is explained; correct option turns green
    at the FINAL ANSWER step)
  * step 1 = "Understand the question" card (GIVEN / TO FIND) built from config
  * solution steps from the reel shown big below (content card left,
    step label + caption + progress bar right)
  * fresh narration with Kokoro TTS (default hf_alpha = Indian-English female);
    every reel step is re-timed to its new narration
  * 16:9 end card

Usage:  python3 make_qtop.py config.json        (see q03.json for all keys)
"""
import json, os, re, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1920, 1080
BG = (239, 239, 229); GRID = (229, 229, 218)
NAVY = (27, 33, 64); OR = (240, 106, 34); GREY = (105, 105, 105)
GREEN = (34, 160, 90); GREEN_BG = (226, 246, 233); LINE = (215, 215, 205)
OR_BG = (253, 236, 224)
FD = '/usr/share/fonts/opentype/inter/'
def F(w, s): return ImageFont.truetype(f'{FD}Inter-{w}.otf', s)
FPS = 30
KEY = "colorkey=0xEFEFE5:0.07:0.05"           # drop reel bg+grid -> transparent

# reel crop (x, y, w, h) -> page (x, y, scale)
TOP_H = 270
CROPS = [  # name, src, dst(x, y), scale, keyed
    ('content', (40, 240, 1000, 900), (36, 270), 0.90, False),
    ('label',   (30, 148, 1020, 92),  (970, 300), 0.90, True),
    ('caption', (40, 1140, 840, 180), (965, 470), 1.10, True),
    ('prog',    (30, 1320, 1030, 240),(975, 800), 0.88, True),
]
GRID_STEP = 54   # page grid; content crop (scale .9, origin multiple of 60) lines up with it

def grid_bg():
    im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)
    for x in range(0, W, GRID_STEP): d.line([(x - 1, 0), (x - 1, H)], fill=GRID, width=2)
    for y in range(0, H, GRID_STEP): d.line([(0, y - 1), (W, y - 1)], fill=GRID, width=2)
    return im

# ---------- rich text: ^{sup} _{sub}; question words may carry a highlight level
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
        dy = -int(sz * 0.18) if k == 'sup' else (int(sz * 0.42) if k == 'sub' else 0)
        d.text((x, y + dy), s, font=ff, fill=col); x += d.textlength(s, font=ff)
    return x

def q_tokens(q):
    """'a [[b c|2]] d' -> [('a',None),('b',2),('c',2),('d',None)]"""
    toks = []
    for part in re.split(r'(\[\[[^\]]*\]\])', q):
        if part.startswith('[['):
            txt, lv = part[2:-2].rsplit('|', 1)
            toks += [(w, int(lv)) for w in txt.split()]
        else:
            for w in part.split():
                if toks and re.match(r'^[.,;:!?)]', w):
                    pw, pl = toks.pop(); toks += [(pw, pl), ('\x00' + w, None)]
                else:
                    toks.append((w, None))
    return toks

def key_logo(frame_png):
    e = np.asarray(Image.open(frame_png).convert('RGB')).astype(float)
    crop = e[480:1010, 270:820]
    B = np.median(e[400:440, 100:200].reshape(-1, 3), axis=0)
    a = np.clip(((B - crop) / B).max(axis=2) * 1.25, 0, 1); a[a < 0.06] = 0
    C = np.clip((crop - (1 - a[..., None]) * B) / np.maximum(a[..., None], 1e-3), 0, 255)
    lg = Image.fromarray(np.dstack([C, a * 255]).astype('uint8'), 'RGBA')
    return lg.crop(lg.getbbox())

# ---------- top question card
def top_card(cfg, logo, hl_level, answered):
    im = Image.new('RGBA', (W, TOP_H), (0, 0, 0, 0))
    sh = Image.new('L', (W, TOP_H), 0)
    ImageDraw.Draw(sh).rounded_rectangle([40, 18, W - 40, TOP_H - 4], 26, fill=70)
    im.paste((150, 150, 140, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([30, 10, W - 30, TOP_H - 12], 26, fill=(255, 255, 255, 255))
    pf = F('Bold', 22); pw = d.textlength(cfg['qno'], font=pf)
    d.rounded_rectangle([66, 24, 66 + pw + 32, 58], 17, fill=(240, 240, 232))
    d.text((82, 28), cfg['qno'], font=pf, fill=NAVY)
    d.text((66 + pw + 52, 30), "TODAY'S QUESTION", font=F('Bold', 20), fill=GREY)
    lg = logo.copy(); lg.thumbnail((80, 46), Image.LANCZOS)
    im.alpha_composite(lg, (W - 66 - lg.width, 18))
    toks = q_tokens(cfg['question']); maxw = W - 132
    for size in (32, 30, 29, 28, 26):
        f, fb, fs = F('SemiBold', size), F('Bold', size), F('SemiBold', int(size * .62))
        sp = d.textlength(' ', font=f); lines, cur, cw = [], [], 0
        for w, lv in toks:
            glue = w.startswith('\x00'); w = w.lstrip('\x00')
            ww = rich_w(d, w, fb if lv else f, fs)
            if cur and not glue and cw + sp + ww > maxw: lines.append(cur); cur, cw = [], 0
            if glue and cur:   # merge into previous word (keeps its colour box tight)
                pw, plv, pww = cur[-1]; cur[-1] = (pw, plv, pww); cur.append((w, None, ww)); cw += ww
                cur[-2] = (pw, plv, pww - 0.0); cur[-1] = ('\x00' + w, None, ww); continue
            cw += (sp if cur else 0) + ww; cur.append((w, lv, ww))
        lines.append(cur)
        if len(lines) <= 3: break
    lh = int(size * 1.3); y = 66 + (3 - len(lines)) * lh // 2
    for ln in lines:
        x = 66
        # highlight boxes first (merge consecutive highlighted words)
        i = 0
        while i < len(ln):
            w, lv, ww = ln[i]
            if lv is not None and lv <= hl_level:
                j, x1 = i, x
                while j < len(ln) and ln[j][1] is not None and ln[j][1] <= hl_level:
                    x1 += ln[j][2] + (sp if j + 1 < len(ln) and ln[j + 1][1] is not None and ln[j + 1][1] <= hl_level else 0)
                    j += 1
                d.rounded_rectangle([x - 5, y - 2, x1 + 5, y + size + 8], 7, fill=OR_BG)
                for k in range(i, j): x += ln[k][2] + sp
                i = j
            else:
                if w.startswith('\x00'): x -= sp
                x += ww + sp; i += 1
        x = 66
        for k2, (w, lv, ww) in enumerate(ln):
            if w.startswith('\x00'): x -= sp; w = w[1:]
            on = lv is not None and lv <= hl_level
            rich(d, x, y, w, fb if on else f, fs, OR if on else NAVY); x += ww + sp
        y += lh
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

# ---------- step-1 card: GIVEN / TO FIND (state after beat b)
def given_card(cfg, b):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    x0, y0, x1, y1 = 48, 296, 940, 1068
    sh = Image.new('L', (W, H), 0)
    ImageDraw.Draw(sh).rounded_rectangle([x0 + 6, y0 + 12, x1 - 6, y1 + 6], 30, fill=60)
    im.paste((150, 150, 140, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0, x1, y1], 30, fill=(255, 255, 255, 255))
    t = 'UNDERSTAND THE QUESTION'; f = F('Bold', 22); tw = d.textlength(t, font=f)
    cx = (x0 + x1) / 2
    d.rounded_rectangle([cx - tw / 2 - 20, y0 + 24, cx + tw / 2 + 20, y0 + 62], 19, fill=(240, 240, 232))
    d.text((cx - tw / 2, y0 + 30), t, font=f, fill=NAVY)
    lf, vf, vfs = F('SemiBold', 26), F('Bold', 34), F('Bold', 22)
    y = y0 + 88
    def head(txt, col):
        nonlocal y
        d.text((x0 + 44, y), txt, font=F('ExtraBold', 26), fill=col)
        d.line([(x0 + 44, y + 38), (x1 - 44, y + 38)], fill=LINE, width=2); y += 52
    def row(lbl, val, col, bg):
        nonlocal y
        d.rounded_rectangle([x0 + 36, y, x1 - 36, y + 62], 14, fill=bg)
        d.text((x0 + 60, y + 16), lbl, font=lf, fill=GREY)
        vw = rich_w(d, val, vf, vfs)
        rich(d, x1 - 60 - vw, y + 11, val, vf, vfs, col); y += 72
    if b >= 1: head('GIVEN', NAVY)
    for lbl, val, bt in cfg['given']:
        if b >= bt: row(lbl, val, NAVY, (246, 246, 240))
    if any(b >= bt for _, _, bt in cfg['find']):
        y += 8; head('TO FIND', OR)
    for lbl, val, bt in cfg['find']:
        if b >= bt: row(lbl, val, OR, OR_BG)
    return im

def end_card(logo):
    im = Image.new('RGB', (W, H), (246, 245, 240))
    v = Image.new('L', (W, H), 0)
    ImageDraw.Draw(v).ellipse([W/2 - 900, H/2 - 650, W/2 + 900, H/2 + 650], fill=255)
    im = Image.composite(Image.new('RGB', (W, H), (252, 251, 248)), im, v.filter(ImageFilter.GaussianBlur(160)))
    d = ImageDraw.Draw(im)
    lg = logo.copy(); lg.thumbnail((420, 330), Image.LANCZOS)
    im.paste(lg, ((W - lg.width) // 2, 180), lg)
    def ct(t, y, f, c): d.text(((W - d.textlength(t, font=f)) / 2, y), t, font=f, fill=c)
    ct('P R A C T I C E   T O D A Y ,   A C H I E V E   T O M O R R O W', 600, F('Bold', 34), NAVY)
    d.line([(W/2 - 60, 680), (W/2 + 60, 680)], fill=OR, width=4)
    ct('cgpedu.com', 715, F('Bold', 48), NAVY)
    return im

# ---------- narration
LEAD, GAP, TAIL, SR = 0.35, 0.35, 0.55, 24000
def narrate(cfg, tmp):
    import soundfile as sf
    from kokoro_onnx import Kokoro
    k = Kokoro(os.path.expanduser('~/kokoro/kokoro-v1.0.onnx'), os.path.expanduser('~/kokoro/voices-v1.0.bin'))
    audio, beat_t, step_t = [], [], []
    t = 0.0
    for beats in cfg['steps']:
        step_t.append(t); bt = []
        audio.append(np.zeros(int(SR * LEAD), np.float32)); t += LEAD
        for i, b in enumerate(beats):
            bt.append(t)
            for s in [p for p in re.split(r'(?<=[.!?])\s+', b) if p]:
                a, _ = k.create(s, voice=cfg.get('voice', 'hf_alpha'), speed=cfg.get('speed', 1.05),
                                lang=cfg.get('lang', 'en-us'))
                audio += [a.astype(np.float32), np.zeros(int(SR * 0.18), np.float32)]
                t += len(a) / SR + 0.18
            if i + 1 < len(beats):
                audio.append(np.zeros(int(SR * GAP), np.float32)); t += GAP
        audio.append(np.zeros(int(SR * TAIL), np.float32)); t += TAIL
        beat_t.append(bt)
    a = np.concatenate(audio)
    sf.write(f'{tmp}/narr.wav', a, SR)
    return step_t, beat_t, t

def main(cfgp):
    cfg = json.load(open(cfgp)); tmp = tempfile.mkdtemp(); v = cfg['video']
    step_t, beat_t, total = narrate(cfg, tmp)
    # last step (end card) must last >= 3 s
    if total - step_t[-1] < 3.0: total = step_t[-1] + 3.0
    print('steps at', [round(x, 2) for x in step_t], 'total', round(total, 2))
    rs = cfg['reel_steps'] + [cfg['reel_end']]
    new_d = [step_t[i + 1] - step_t[i] for i in range(len(step_t) - 1)] + [total - step_t[-1]]
    # 1) re-timed reel
    parts, labels = [], []
    for i in range(len(new_d)):
        f = new_d[i] / (rs[i + 1] - rs[i])
        parts.append(f"[0:v]trim={rs[i]}:{rs[i+1]},setpts=(PTS-STARTPTS)*{f:.5f},fps={FPS},"
                     f"trim=duration={new_d[i]:.4f}[r{i}]")
        labels.append(f'[r{i}]')
    parts.append(''.join(labels) + f"concat=n={len(labels)}:v=1:a=0[o]")
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', v, '-filter_complex', ';'.join(parts),
                    '-map', '[o]', '-c:v', 'libx264', '-crf', '14', '-preset', 'fast', f'{tmp}/reel.mp4'],
                   check=True)
    # 2) still layers
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-sseof', '-0.5', '-i', v, '-frames:v', '1',
                    f'{tmp}/end.png'], check=True)
    logo = key_logo(f'{tmp}/end.png')
    grid_bg().save(f'{tmp}/bg.png'); end_card(logo).save(f'{tmp}/endcard.png')
    s1 = beat_t[0]; s1_end = step_t[1]; ans = step_t[cfg['answer_step']]; endt = step_t[-1]
    layers = []   # (png, start, end)
    for b in range(len(s1)):
        top_card(cfg, logo, b, False).save(f'{tmp}/top_b{b}.png')
        given_card(cfg, b).save(f'{tmp}/giv_b{b}.png')
        e = s1[b + 1] if b + 1 < len(s1) else s1_end
        layers += [(f'{tmp}/giv_b{b}.png', s1[b] if b else 0, e), (f'{tmp}/top_b{b}.png', s1[b] if b else 0, e)]
    top_card(cfg, logo, 99, False).save(f'{tmp}/top_all.png')
    top_card(cfg, logo, 99, True).save(f'{tmp}/top_ans.png')
    layers += [(f'{tmp}/top_all.png', s1_end, ans), (f'{tmp}/top_ans.png', ans, total + 1)]
    # 3) compose
    inp = ['-loop', '1', '-framerate', str(FPS), '-i', f'{tmp}/bg.png', '-i', f'{tmp}/reel.mp4',
           '-i', f'{tmp}/narr.wav']
    fc = [f"[1:v]split={len(CROPS)}" + ''.join(f'[s{i}]' for i in range(len(CROPS)))]
    for i, (n, (x, y, w, h), _, sc, keyed) in enumerate(CROPS):
        fc.append(f"[s{i}]crop={w}:{h}:{x}:{y},scale={round(w*sc)}:{round(h*sc)}:flags=lanczos"
                  + (f",format=rgba,{KEY}" if keyed else '') + f"[{n}]")
    cur = '0:v'
    for i, (n, _, (px, py), _, _) in enumerate(CROPS):
        fc.append(f"[{cur}][{n}]overlay={px}:{py}[c{i}]"); cur = f'c{i}'
    idx = 3
    for j, (png, a, b) in enumerate(layers):
        inp += ['-loop', '1', '-framerate', str(FPS), '-i', png]
        fc.append(f"[{cur}][{idx}:v]overlay=0:0:enable='between(t,{a:.3f},{b - 0.001:.3f})'[l{j}]")
        cur = f'l{j}'; idx += 1
    inp += ['-loop', '1', '-framerate', str(FPS), '-i', f'{tmp}/endcard.png']
    fc.append(f"[{idx}:v]format=rgba,fade=t=in:st={endt:.3f}:d=0.4:alpha=1[ec]")
    fc.append(f"[{cur}][ec]overlay=0:0:enable='gte(t,{endt:.3f})',format=yuv420p[out]")
    subprocess.run(['ffmpeg', '-v', 'error', '-y'] + inp + ['-filter_complex', ';'.join(fc),
                    '-map', '[out]', '-map', '2:a', '-t', f'{total:.3f}', '-c:v', 'libx264', '-crf', '18',
                    '-preset', 'medium', '-r', str(FPS), '-c:a', 'aac', '-b:a', '160k',
                    '-af', 'apad', '-movflags', '+faststart', cfg['out']], check=True)
    print('done ->', cfg['out'])

if __name__ == '__main__':
    main(sys.argv[1])
