"""Render a Mega Man X1 level (foreground) to PNG straight from the ROM.

usage: python3 render_level.py <level> [checkpoint] [--bg] [--events] [--collision] [--locks] [--rom=path]
"""
import sys
from PIL import Image, ImageDraw
from mmx1 import MMX1, decode_4bpp, collision_name

ROM = "../Mega Man X (USA) (Rev 1).sfc"


def render(g: MMX1, level, checkpoint=0, background=False, events=False, collision=False, locks=False):
    ptr = g.level_ptrs(level, background)
    pal = g.palette(level, checkpoint)
    vram = g.vram(level, checkpoint)
    tiles = [decode_4bpp(vram[i*32:i*32+32]) for i in range(0x400)]
    width, height, used, cells = g.layout(level, background)

    tile_cache = {}

    def tile_img(word):
        # SNES BG tilemap word: vhopppcc cccccccc
        if word not in tile_cache:
            px = tiles[word & 0x3FF]
            p = (word >> 10) & 7
            im = Image.new("RGB", (8, 8))
            im.putdata([pal[p*16 + v] for v in px])
            if word & 0x4000: im = im.transpose(Image.FLIP_LEFT_RIGHT)
            if word & 0x8000: im = im.transpose(Image.FLIP_TOP_BOTTOM)
            tile_cache[word] = im
        return tile_cache[word]

    map_cache = {}

    def map_img(m):
        if m not in map_cache:
            im = Image.new("RGB", (16, 16))
            base = ptr["maps"] + m * 8
            for i in range(4):
                im.paste(tile_img(g.w(base + i*2)), ((i & 1) * 8, (i >> 1) * 8))
            map_cache[m] = im
        return map_cache[m]

    def block_img(b):
        im = Image.new("RGB", (32, 32))
        base = ptr["blocks"] + b * 8
        for i in range(4):
            im.paste(map_img(g.w(base + i*2)), ((i & 1) * 16, (i >> 1) * 16))
        return im

    scene_cache = {}

    def scene_img(s):
        if s not in scene_cache:
            im = Image.new("RGB", (256, 256))
            base = ptr["scenes"] + s * 0x80
            for i in range(64):
                im.paste(block_img(g.w(base + i*2)), ((i % 8) * 32, (i // 8) * 32))
            scene_cache[s] = im
        return scene_cache[s]

    out = Image.new("RGB", (width * 256, height * 256))
    for i, s in enumerate(cells[:width * height]):
        out.paste(scene_img(s), ((i % width) * 256, (i // width) * 256))

    if collision and not background:
        # tint each 16x16 map by its collision class
        tint = {"slope": (255, 160, 0), "water": (0, 120, 255), "ladder": (0, 255, 0),
                "conveyor": (255, 0, 255), "spikes": (255, 0, 0), "solid": (255, 255, 255)}
        overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for i, s in enumerate(cells[:width * height]):
            sx, sy = (i % width) * 256, (i // width) * 256
            for bi in range(64):
                b = g.w(ptr["scenes"] + s * 0x80 + bi * 2)
                bx, by = sx + (bi % 8) * 32, sy + (bi // 8) * 32
                for k in range(4):
                    m = g.w(ptr["blocks"] + b * 8 + k * 2)
                    c = g.rom[ptr["collision"] + m]
                    if not c:
                        continue
                    name = collision_name(c)
                    col = next((v for key, v in tint.items() if name.startswith(key)), (128, 128, 128))
                    x0, y0 = bx + (k & 1) * 16, by + (k >> 1) * 16
                    od.rectangle([x0, y0, x0 + 15, y0 + 15], fill=col + (90,))
        out = Image.alpha_composite(out.convert("RGBA"), overlay).convert("RGB")

    if locks and not background:
        d = ImageDraw.Draw(out)
        for lk in g.camera_locks(level):
            d.rectangle([lk["left"], lk["top"], lk["right"], lk["bottom"]], outline="magenta", width=2)
            txt = " ".join(f"{n}={v:X}" for _, v, n in lk["locks"])
            d.text((lk["left"] + 2, lk["top"] + 2), f"L{lk['index']:X} {txt}", fill="magenta")

    if events:
        d = ImageDraw.Draw(out)
        colors = {0: "yellow", 1: "cyan", 2: "lime", 3: "red"}
        for e in g.events(level):
            c = colors[e.type]
            d.rectangle([e.x - 8, e.y - 8, e.x + 8, e.y + 8], outline=c, width=2)
            d.text((e.x + 10, e.y - 8), f"{e.type}:{e.id:02X}.{e.sub:02X}", fill=c)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    level = int(args[0], 0)
    cp = int(args[1], 0) if len(args) > 1 else 0
    rom = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--rom=")), ROM)
    g = MMX1(rom)
    img = render(g, level, cp, "--bg" in sys.argv, "--events" in sys.argv,
                 "--collision" in sys.argv, "--locks" in sys.argv)
    name = f"out/level{level:02d}{'_bg' if '--bg' in sys.argv else ''}.png"
    import os; os.makedirs("out", exist_ok=True)
    img.save(name)
    print(name, img.size)
