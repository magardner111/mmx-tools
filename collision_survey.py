"""Group 16x16 maps by collision byte across all levels and build a contact sheet per value."""
from collections import Counter, defaultdict
from PIL import Image, ImageDraw
from mmx1 import MMX1, decode_4bpp, NUM_LEVELS

g = MMX1("../Mega Man X (USA) (Rev 1).sfc")
examples = defaultdict(list)
counts = Counter()

for L in range(NUM_LEVELS):
    ptr = g.level_ptrs(L)
    pal = g.palette(L); vram = g.vram(L)
    tiles = [decode_4bpp(vram[i*32:i*32+32]) for i in range(0x400)]
    w, h, used, cells = g.layout(L)
    maps_used = Counter()
    for s in cells[:w*h]:
        for i in range(64):
            b = g.w(ptr["scenes"] + s*0x80 + i*2)
            for j in range(4):
                maps_used[g.w(ptr["blocks"] + b*8 + j*2)] += 1
    for m, n in maps_used.items():
        c = g.rom[ptr["collision"] + m]
        counts[c] += n
        if len(examples[c]) < 24:
            im = Image.new("RGB", (16, 16))
            for k in range(4):
                word = g.w(ptr["maps"] + m*8 + k*2)
                t = Image.new("RGB", (8, 8))
                p = (word >> 10) & 7
                t.putdata([pal[p*16+v] for v in tiles[word & 0x3FF]])
                if word & 0x4000: t = t.transpose(Image.FLIP_LEFT_RIGHT)
                if word & 0x8000: t = t.transpose(Image.FLIP_TOP_BOTTOM)
                im.paste(t, ((k & 1)*8, (k >> 1)*8))
            examples[c].append((L, m, im))

vals = sorted(examples)
print("collision values (value: placed-count):")
print(", ".join(f"{v:02X}:{counts[v]}" for v in vals))
S = 3
sheet = Image.new("RGB", (60 + 24*18*S, len(vals)*18*S + 4), (40, 40, 40))
d = ImageDraw.Draw(sheet)
for r, v in enumerate(vals):
    d.text((4, r*18*S + 16), f"{v:02X}", fill="white")
    for c, (L, m, im) in enumerate(examples[v]):
        sheet.paste(im.resize((16*S, 16*S), Image.NEAREST), (60 + c*18*S, r*18*S + 2))
sheet.save("out/collision_sheet.png")
