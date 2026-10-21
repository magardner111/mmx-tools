"""
Draw an enemy's sprite (first frame of its sprite assembly) from the X1 ROM.

Port of MegaEdX RenderED::RenderEvent/RenderObject for X1:
  $86A5E4 + (id-1)*2      : assembly number, graphics number for enemy id
  $86F6F7 + gfx*5         : word size, long pointer -> X1-compressed 4bpp tiles
  $86ACEE / $86ACF1       : per-stage object-graphics lists (6-byte entries: gfx, ..., palette word)
  $868133 + palette word  : palette config (count byte, word ptr into bank $85) -> 16 colours
  $8D8000 + asm*3         : long ptr -> frame pointer list; frame 0 -> count, then 4-byte pieces
                            (x s8, y s8, tile, info: bit5 = 16x16, bit6 = h-flip, bit7 = v-flip)

usage: python3 sprites.py [id_hex ...]     (no args: contact sheet of all enemies -> out/enemy_sprites.png)
"""
import sys
from functools import lru_cache

from PIL import Image, ImageDraw

from mmx1 import MMX1, snes2pc, decode_4bpp, x1_decompress, snes_color, LEVEL_NAMES

ROM = "../Mega Man X (USA) (Rev 1).sfc"
SPRITE_OFFSET = 0x86A5E4
GFX_LIST = 0x86F6F7
GFX_OBJ = 0x86ACEE
GFX_PAL = 0x86ACF1
PAL_BASE = 0x868133
ASSEMBLY = 0x8D8000


def sprite_ids(g, enemy_id):
    o = snes2pc(SPRITE_OFFSET) + (enemy_id - 1) * 2
    return g.rom[o], g.rom[o + 1]          # assembly, gfx


def graphics_palettes(g):
    """gfx number -> palette word, gathered from every stage's object-graphics sets."""
    base, pal = snes2pc(GFX_OBJ), snes2pc(GFX_PAL)
    out = {}
    for L in range(len(LEVEL_NAMES)):
        level_off = g.w(base + L * 2)
        for n in range(16):
            obj_off = g.w(base + level_off + n * 2)
            if obj_off > 0x4000:
                break
            k = 0
            while k < 64:
                gfx = g.rom[base + obj_off]
                if gfx == 0xFF:
                    break
                out.setdefault(gfx, g.w(pal + obj_off))
                obj_off += 6
                k += 1
    return out


def palette(g, pal_num):
    cfg = snes2pc(0x860000 | ((g.w(snes2pc(PAL_BASE) + pal_num) + 1) & 0xFFFF))
    colors = snes2pc(0x850000 | g.w(cfg))
    return [snes_color(g.w(colors + i * 2)) for i in range(16)]


def gfx_tiles(g, gfx):
    e = snes2pc(GFX_LIST) + gfx * 5
    size = min(g.w(e), 0x20000)
    src = snes2pc(g.l(e + 2))
    data = x1_decompress(g.rom, src, size)
    return [decode_4bpp(data[i * 32:i * 32 + 32]) for i in range(len(data) // 32)]


def frame_pieces(g, assembly, frame=0):
    frames = snes2pc(g.l(snes2pc(ASSEMBLY) + assembly * 3))
    base = snes2pc(g.l(frames + frame))
    count = g.rom[base]
    if count > 64:
        return []
    pieces = []
    for i in range(count):
        p = base + 1 + i * 4
        x, y = g.rom[p], g.rom[p + 1]
        pieces.append((x - 256 if x > 127 else x, y - 256 if y > 127 else y, g.rom[p + 2], g.rom[p + 3]))
    return pieces


class SpriteRenderer:
    def __init__(self, g):
        self.g = g
        self.pal_map = graphics_palettes(g)
        self._tiles = {}

    def tiles(self, gfx):
        if gfx not in self._tiles:
            self._tiles[gfx] = gfx_tiles(self.g, gfx)
        return self._tiles[gfx]

    def render(self, enemy_id, scale=3, frame=0):
        """RGBA image of the enemy's first frame, or None if it has no usable sprite."""
        try:
            assembly, gfx = sprite_ids(self.g, enemy_id)
            tiles = self.tiles(gfx)
            pal = palette(self.g, self.pal_map.get(gfx, 0))
            pieces = frame_pieces(self.g, assembly, frame)
        except (IndexError, ValueError):
            return None
        if not pieces or not tiles:
            return None
        canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        ox, oy = 128, 128
        # pieces are listed front-to-back; draw back-to-front
        for x, y, tile, info in reversed(pieces):
            large = info & 0x20
            h, v = (info >> 6) & 1, (info >> 7) & 1
            for j in range(4 if large else 1):
                t_off = (j ^ (h if large else 0) ^ ((v << 1) if large else 0)) if large else j
                t = tile + (t_off % 2) + (t_off // 2) * 16
                if t >= len(tiles):
                    continue
                im = Image.new("RGBA", (8, 8))
                im.putdata([(0, 0, 0, 0) if c == 0 else pal[c] + (255,) for c in tiles[t]])
                if h:
                    im = im.transpose(Image.FLIP_LEFT_RIGHT)
                if v:
                    im = im.transpose(Image.FLIP_TOP_BOTTOM)
                canvas.alpha_composite(im, (ox + x + (j % 2) * 8, oy + y + (j // 2) * 8))
        box = canvas.getbbox()
        if not box:
            return None
        canvas = canvas.crop(box)
        if scale != 1:
            canvas = canvas.resize((canvas.width * scale, canvas.height * scale), Image.NEAREST)
        return canvas


@lru_cache(maxsize=1)
def renderer_for_stock():
    return SpriteRenderer(MMX1(ROM))


if __name__ == "__main__":
    g = MMX1(ROM)
    r = SpriteRenderer(g)
    ids = [int(a, 16) for a in sys.argv[1:]] or list(range(1, 0x6C))
    cell = 120
    cols = 12
    sheet = Image.new("RGB", (cols * cell, ((len(ids) + cols - 1) // cols) * (cell + 14)), (60, 60, 70))
    d = ImageDraw.Draw(sheet)
    ok = 0
    for n, i in enumerate(ids):
        im = r.render(i, scale=2)
        cx, cy = (n % cols) * cell, (n // cols) * (cell + 14)
        d.text((cx + 3, cy + 2), f"{i:02X}", fill="white")
        if im:
            ok += 1
            im.thumbnail((cell - 8, cell - 8))
            sheet.paste(im, (cx + (cell - im.width) // 2, cy + 14 + (cell - im.height) // 2), im)
    sheet.save("out/enemy_sprites.png")
    print(f"rendered {ok}/{len(ids)} -> out/enemy_sprites.png")
