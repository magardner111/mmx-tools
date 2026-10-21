"""
MMX Lab: a small Tk editor for the Mega Man X1 data we've decoded.

    python3 ui.py [project.sfc]

Works on a project ROM (default work/hack.sfc, copied from the stock ROM the
first time). The stock ROM is never written.
"""
import base64
import io
import json
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from PIL import Image
try:
    from PIL import ImageTk
except ImportError:     # Debian/Raspberry Pi OS ship ImageTk separately (python3-pil.imagetk)
    ImageTk = None
from sprites import SpriteRenderer
import gfxsets as G

import params as P
from defs import BOSSES, PROJECTILES, NUM_PROJECTILES
from mmx1 import MMX1, LEVEL_NAMES, save_rom
from render_level import render
from trace import listing
from lift import lift
from decomp import decompile_with_map
from testwarp import make_test_rom
import re

HERE = Path(__file__).parent
DEFAULT_PROJECT = HERE / "work" / "hack.sfc"
SETTINGS = HERE / "mmxlab.json"
MAC = sys.platform == "darwin"
WINDOWS = sys.platform.startswith("win")
EMU_DIR = HERE.parent / "emulator"
EMULATOR_CANDIDATES = [EMU_DIR / "snes9x-gtk", EMU_DIR / "snes9x.exe",
                       EMU_DIR / "Mesen.app" / "Contents" / "MacOS" / "Mesen", EMU_DIR / "Mesen.exe",
                       EMU_DIR / "Mesen", EMU_DIR / "Mesen.AppImage"]
DEFAULT_EMULATOR = next((p for p in EMULATOR_CANDIDATES if p.is_file()), None)


def load_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(data):
    SETTINGS.write_text(json.dumps(data, indent=2))
MONO_FAMILY = "Menlo" if MAC else "Consolas" if WINDOWS else "DejaVu Sans Mono"
MOD = "Command" if MAC else "Control"     # modifier for keyboard shortcuts

# Named fonts, all resized together by the Text size setting: name -> (family, size at 100%, weight).
# A family of None means the normal UI font.
FONTS = {"Title": (None, 18, "bold"), "Heading": (None, 13, "bold"), "Subheading": (None, 12, "bold"),
         "Bold": (None, 11, "bold"), "SmallBold": (None, 10, "bold"), "Small": (None, 9, "normal"),
         "Mono": (MONO_FAMILY, 11, "normal"), "MonoBold": (MONO_FAMILY, 11, "bold"),
         "MonoSmall": (MONO_FAMILY, 10, "normal"), "MonoTiny": (MONO_FAMILY, 9, "normal")}
TK_FONTS = ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
            "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")
SCALES = [70, 80, 90, 100, 110, 125, 150]
UI_SCALE = 1.0      # current Text size; px() scales pixel sizes (wrap widths, column widths) to match


def px(n):
    return int(n * UI_SCALE)


def photo(img):
    """A Tk image from a PIL image, with or without PIL's ImageTk module."""
    if ImageTk is not None:
        return ImageTk.PhotoImage(img)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return tk.PhotoImage(data=base64.b64encode(buf.getvalue()))


_WHEEL_TARGETS = {}     # canvas -> active() for every canvas that scrolls with the mouse wheel


def bind_wheel(widget, canvas, active):
    """Scroll `canvas` with the mouse wheel (Shift: sideways) while the pointer is over it and `active()`
    is true, on every platform. Widgets that scroll themselves (text, lists, tables) keep their own wheel."""
    _WHEEL_TARGETS[canvas] = active
    if len(_WHEEL_TARGETS) > 1:
        return

    def wheel(e):
        w = e.widget.winfo_containing(e.x_root, e.y_root)
        if w is None or isinstance(w, (tk.Text, tk.Listbox, ttk.Treeview)):
            return
        while w is not None and w not in _WHEEL_TARGETS:
            w = w.master
        if w is None or not w.winfo_exists() or not _WHEEL_TARGETS[w]():
            return
        if e.num == 4 or e.num == 5:                    # X11 (Linux) sends buttons 4/5
            step = -1 if e.num == 4 else 1
        elif WINDOWS:                                   # Windows: multiples of 120
            step = -e.delta // 120
        else:                                           # macOS: small deltas
            step = -e.delta
        (w.xview_scroll if e.state & 1 else w.yview_scroll)(step, "units")
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        widget.bind_all(seq, wheel)


class ScrollFrame(ttk.Frame):
    """A frame whose `body` scrolls in either direction once it no longer fits; while it fits, `body`
    is stretched to fill the visible area. Scrollbars appear only when needed."""
    def __init__(self, parent, track_width=False, **kw):
        super().__init__(parent, **kw)
        self.track_width = track_width      # ask for the body's full width rather than a default
        bg = ttk.Style(self).lookup("TFrame", "background") or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=bg)
        self.vs = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hs = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vs.set, xscrollcommand=self.hs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body = ttk.Frame(self.canvas)
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.fit())
        bind_wheel(self.canvas, self.canvas, self.winfo_ismapped)
        self._last = None
        self._poll()

    def _poll(self):
        # the body's requested size changes without any event, so check for it a few times a second
        if self.winfo_ismapped():
            self.fit()
        self.after(250, self._poll)

    def fit(self):
        need = (self.body.winfo_reqwidth(), self.body.winfo_reqheight())
        have = (self.canvas.winfo_width(), self.canvas.winfo_height())
        if (need, have) == self._last:
            return
        self._last = (need, have)
        if self.track_width and int(self.canvas.cget("width")) != need[0]:
            self.canvas.configure(width=need[0])    # asks for the body's width; a squeezed pane still scrolls
        w, h = max(need[0], have[0]), max(need[1], have[1])
        self.canvas.itemconfigure(self.item, width=w, height=h)
        self.canvas.configure(scrollregion=(0, 0, w, h))
        for bar, n, v, place in ((self.vs, need[1], have[1], dict(row=0, column=1, sticky="ns")),
                                 (self.hs, need[0], have[0], dict(row=1, column=0, sticky="ew"))):
            if n > v + 1:
                bar.grid(**place)
            elif n < v - 20 or (bar is self.hs and self.track_width and n <= v):
                bar.grid_remove()   # (the margin stops a scrollbar appearing/disappearing from flip-flopping)
EVENT_TYPES = {0: "item/door", 1: "script", 2: "trigger", 3: "enemy"}


class App(tk.Tk):
    def __init__(self, project: Path):
        super().__init__()
        ttk.Style(self).configure("Mod.TEntry", foreground="#b00020")
        self.init_fonts()
        self.fit_to_screen()
        self.project = None
        self.g = None
        self.dirty = False

        self._build_toolbar()
        self.status = ttk.Label(self, anchor="w", padding=(8, 2))
        self.status.pack(fill="x", side="bottom")   # packed before the tabs so a short window can't hide it
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self.boss_tab = BossTab(self.nb, self)
        self.enemy_tab = EnemyTab(self.nb, self)
        self.level_tab = LevelTab(self.nb, self)
        self.code_tab = CodeTab(self.nb, self)
        for tab, name in ((self.boss_tab, "Bosses"), (self.enemy_tab, "Enemies"),
                          (self.level_tab, "Levels"), (self.code_tab, "Code")):
            self.nb.add(tab, text=name)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all(f"<{MOD}-s>", lambda e: self.save())
        self.bind_all(f"<{MOD}-r>", lambda e: self.save_and_run())
        for seq, d in (("equal", 1), ("plus", 1), ("minus", -1)):
            self.bind_all(f"<{MOD}-{seq}>", lambda e, d=d: self.step_scale(d))
        self.emu_proc = None
        self.open_project(project)

    # --- window size and text size ----------------------------------------------------------
    def fit_to_screen(self):
        """Open at 1280x820, or smaller so the whole window (title bar and taskbar included) is on screen."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1280, sw - 40), min(820, sh - 100)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h - 60) // 2)}")
        self.minsize(min(640, w), min(420, h))

    def init_fonts(self):
        import tkinter.font as tkfont
        self.base_sizes = {}
        for name in TK_FONTS:
            try:
                self.base_sizes[name] = tkfont.nametofont(name).cget("size")
            except tk.TclError:
                pass
        ui_family = tkfont.nametofont("TkDefaultFont").cget("family")
        self.fonts = {}     # Tk deletes a named font when its Python object goes away
        for name, (family, size, weight) in FONTS.items():
            self.fonts[name] = tkfont.Font(self, name=name, family=family or ui_family, size=size, weight=weight)
            self.base_sizes[name] = size
        self.scale = 100
        self.apply_scale(load_settings().get("text_size", 100))

    def apply_scale(self, pct):
        """Resize every font, then the pixel sizes tied to text (wrap widths, table columns and rows)."""
        import tkinter.font as tkfont
        global UI_SCALE
        pct = min(SCALES, key=lambda s: abs(s - pct))
        ratio = pct / self.scale
        if not hasattr(self, "base_px"):
            self.base_px = {}   # (widget, setting) -> its size at 100%, so repeated changes don't drift
        for name, size in self.base_sizes.items():
            new = round(abs(size) * pct / 100)
            tkfont.nametofont(name).configure(size=max(6, new) * (-1 if size < 0 else 1))
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(self).configure("Treeview", rowheight=line + 4)
        old, self.scale, UI_SCALE = UI_SCALE, pct, pct / 100
        if ratio != 1:
            self._rescale_widgets(self, old)
        if hasattr(self, "scale_box"):
            self.scale_box.set(f"{pct}%")

    def _rescale_widgets(self, w, old):
        def base(key, current):
            return self.base_px.setdefault((str(w), key), current / old)
        if isinstance(w, ttk.Treeview):
            for c in w["columns"]:
                w.column(c, width=px(base(c, w.column(c, "width"))),
                         minwidth=px(base(c + "/min", w.column(c, "minwidth"))))
        else:
            try:
                wrap = int(str(w.cget("wraplength")) or 0)
                if wrap > 0:
                    w.configure(wraplength=px(base("wrap", wrap)))
            except (tk.TclError, ValueError):
                pass
        for child in w.winfo_children():
            self._rescale_widgets(child, old)

    def set_scale(self, pct):
        self.apply_scale(pct)
        data = load_settings()
        data["text_size"] = self.scale
        save_settings(data)
        self.set_status(f"Text size {self.scale}%")

    def step_scale(self, d):
        i = SCALES.index(self.scale) + d
        if 0 <= i < len(SCALES):
            self.set_scale(SCALES[i])

    # --- project -------------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        ttk.Button(bar, text="Open…", command=self.ask_open).pack(side="left")
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", padx=4)
        ttk.Button(bar, text="Save As…", command=self.save_as).pack(side="left")
        ttk.Button(bar, text="Reload", command=lambda: self.open_project(self.project)).pack(side="left", padx=4)
        self.expand_btn = ttk.Button(bar, text="Expand ROM…", command=self.expand_rom)
        self.expand_btn.pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="▶ Save & Run", command=self.save_and_run).pack(side="left")
        ttk.Button(bar, text="Emulator…", command=self.choose_emulator).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(bar, text="Text size").pack(side="left")
        self.scale_box = ttk.Combobox(bar, state="readonly", width=5, values=[f"{s}%" for s in SCALES])
        self.scale_box.set(f"{self.scale}%")
        self.scale_box.pack(side="left", padx=4)
        self.scale_box.bind("<<ComboboxSelected>>", lambda e: self.set_scale(int(self.scale_box.get()[:-1])))
        self.path_label = ttk.Label(bar, foreground="#555")
        self.path_label.pack(side="left", padx=12)

    def open_project(self, path: Path):
        if self.dirty and not messagebox.askyesno("Discard changes?", "Discard unsaved changes?"):
            return
        path = Path(path)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(P.STOCK_ROM, path)
        self.project = path
        self.g = MMX1(path)
        self.dirty = False
        for tab in (self.boss_tab, self.enemy_tab, self.level_tab, self.code_tab):
            tab.refresh()
        self.update_title()

    # --- emulator ------------------------------------------------------------------------
    def emulator_path(self):
        p = load_settings().get("emulator")
        if p and Path(p).exists():
            return Path(p)
        return DEFAULT_EMULATOR

    def choose_emulator(self):
        f = filedialog.askopenfilename(title="Choose an emulator (app or executable)",
                                       initialdir=str(EMU_DIR if EMU_DIR.is_dir() else HERE.parent))
        if not f:
            return
        p = Path(f)
        if p.suffix == ".app":      # use the executable inside the bundle
            exe = next((x for x in (p / "Contents" / "MacOS").iterdir() if x.is_file() and x.stat().st_mode & 0o111), None)
            p = exe or p
        data = load_settings()
        data["emulator"] = str(p)
        save_settings(data)
        self.set_status(f"Emulator: {p}")

    def save_and_run(self):
        if not self._guard(self.project):
            return
        if self.need_emulator():
            self.save()
            if self.launch(self.project):
                self.set_status(f"Saved {self.project.name} and launched {self.emulator_path().name}")

    def run_test(self, level, x, y=None):
        """Build work/test.sfc from the ROM as edited (no save needed) starting at (x, y) and run it."""
        if not self.need_emulator():
            return
        try:
            t = make_test_rom(self.g, level, x, y)
        except ValueError as e:
            messagebox.showerror("Can't build test ROM", str(e))
            return
        out = HERE / "work" / "test.sfc"
        save_rom(t, out)
        if self.launch(out):
            cp = t.checkpoint(level, 0)
            self.set_status(f"Testing {LEVEL_NAMES[level]} from ({cp['chX']}, {cp['chY']}) — {out.name}")

    def need_emulator(self):
        if self.emulator_path() is None:
            messagebox.showinfo("No emulator", "Choose an emulator first (Emulator… button).")
            self.choose_emulator()
        return self.emulator_path() is not None

    def launch(self, rom: Path):
        if self.emu_proc and self.emu_proc.poll() is None:     # restart our previous emulator window
            self.emu_proc.terminate()
            try:
                self.emu_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.emu_proc.kill()
        try:
            self.emu_proc = subprocess.Popen([str(self.emulator_path()), str(rom.resolve())],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            messagebox.showerror("Can't start emulator", str(e))
            return False
        return True

    def expand_rom(self):
        """Grow the project ROM to 2.5 MB (room for more events, layouts, scenes)."""
        if self.g.expanded:
            messagebox.showinfo("Expand ROM", "This project is already expanded.")
            return
        if not messagebox.askyesno("Expand ROM",
                                   "Expand this project to 2.5 MB? Events, layouts, scenes, checkpoints and camera "
                                   "locks move to new banks (2 KB of events per stage). Your current edits are kept. "
                                   "This can't be undone except by reverting the file."):
            return
        from expand import expand
        try:
            self.g = MMX1(expand(bytearray(self.g.rom)))
        except ValueError as e:
            messagebox.showerror("Can't expand", str(e))
            return
        for tab in (self.boss_tab, self.enemy_tab, self.level_tab, self.code_tab):
            tab.refresh()
        self.changed("ROM expanded to 2.5 MB — save to keep it")

    def ask_open(self):
        f = filedialog.askopenfilename(initialdir=HERE / "work", filetypes=[("SNES ROM", "*.sfc *.smc")])
        if f:
            self.open_project(Path(f))

    def _guard(self, path: Path):
        if path.resolve() == P.STOCK_ROM.resolve():
            messagebox.showerror("Not allowed", "That's the original ROM. Save to a different file.")
            return False
        return True

    def save(self):
        if not self._guard(self.project):
            return
        save_rom(self.g, self.project)
        self.dirty = False
        self.update_title()
        self.set_status(f"Saved {self.project.name}")

    def save_as(self):
        f = filedialog.asksaveasfilename(initialdir=HERE / "work", defaultextension=".sfc",
                                         filetypes=[("SNES ROM", "*.sfc")])
        if f and self._guard(Path(f)):
            self.project = Path(f)
            self.save()

    def changed(self, msg=""):
        self.dirty = True
        self.update_title()
        if msg:
            self.set_status(msg)

    def update_title(self):
        exp = " · expanded" if self.g.expanded else ""
        if hasattr(self, "expand_btn"):
            self.expand_btn.state(["disabled"] if self.g.expanded else ["!disabled"])
        self.title(f"MMX Lab — {self.project.name}{' •' if self.dirty else ''}")
        self.path_label.config(text=f"{self.project}{exp}")

    def set_status(self, msg):
        self.status.config(text=msg)

    def on_close(self):
        if self.dirty:
            r = messagebox.askyesnocancel("Save changes?", f"Save changes to {self.project.name}?")
            if r is None:
                return
            if r:
                self.save()
        self.destroy()


# ---------------------------------------------------------------------------------------
class BossTab(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, padding=8)
        self.app = app
        left = ttk.Frame(self)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Bosses", font="Heading").pack(anchor="w")
        self.boss_list = tk.Listbox(left, width=22, exportselection=False)
        self.boss_list.pack(fill="y", expand=True, pady=4)
        for b in BOSSES.values():
            self.boss_list.insert("end", b.name)
        self.boss_list.bind("<<ListboxSelect>>", lambda e: self.show_boss())

        # scrollable right side
        outer = ScrollFrame(self)
        outer.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.body = outer.body
        self.boss = None

    def refresh(self):
        if not self.boss_list.curselection():
            self.boss_list.selection_set(0)
        self.show_boss()

    def show_boss(self):
        sel = self.boss_list.curselection()
        if not sel:
            return
        self.boss = list(BOSSES.values())[sel[0]]
        for w in self.body.winfo_children():
            w.destroy()
        b, g = self.boss, self.app.g

        ttk.Label(self.body, text=b.name, font="Title").grid(row=0, column=0, columnspan=6, sticky="w")
        info = f"object {b.object_id:02X} · stage: {LEVEL_NAMES[b.level]} · code ${b.routine:06X}"
        if b.damage_class is not None:
            info += f" · damage class {b.damage_class}"
        ttk.Label(self.body, text=info, foreground="#666").grid(row=1, column=0, columnspan=5, sticky="w")
        ttk.Label(self.body, text=b.summary, wraplength=px(820), justify="left").grid(
            row=2, column=0, columnspan=6, sticky="w", pady=(6, 10))
        ttk.Button(self.body, text="View code", command=lambda: self.app.code_tab.show(b.routine)).grid(
            row=1, column=5, sticky="e")

        r = 3
        if b.weakness:
            ttk.Label(self.body, text=f"Weakness: {b.weakness}", font="Subheading").grid(
                row=r, column=0, columnspan=6, sticky="w", pady=(0, 6))
            r += 1
        for note in b.notes:
            ttk.Label(self.body, text="• " + note, foreground="#555", wraplength=px(820), justify="left").grid(
                row=r, column=0, columnspan=6, sticky="w")
            r += 1

        # attacks
        if b.attacks_doc:
            ttk.Label(self.body, text="Attacks", font="Heading").grid(row=r, column=0, sticky="w")
            r += 1
            for name, doc in b.attacks_doc.items():
                ttk.Label(self.body, text=name, font="Bold").grid(row=r, column=0, sticky="nw", padx=(0, 8))
                ttk.Label(self.body, text=doc, wraplength=px(700), justify="left").grid(
                    row=r, column=1, columnspan=5, sticky="w")
                r += 1

        # parameters
        ttk.Separator(self.body).grid(row=r, column=0, columnspan=6, sticky="ew", pady=10)
        r += 1
        ttk.Label(self.body, text="Parameters", font="Heading").grid(row=r, column=0, sticky="w")
        r += 1
        for c, h in enumerate(["Setting", "Value", "", "Meaning", "Stock", ""]):
            ttk.Label(self.body, text=h, foreground="#666").grid(row=r, column=c, sticky="w", padx=4)
        r += 1
        self.param_rows = []
        for p in b.params:
            v = P.get(g, p)
            ttk.Label(self.body, text=p.label).grid(row=r, column=0, sticky="w", padx=4, pady=1)
            var = tk.StringVar(value=str(v))
            meaning = ttk.Label(self.body, text=P.describe(p, v), width=26)
            meaning.grid(row=r, column=3, sticky="w", padx=4)
            lo, hi = P.limits(p)
            if p.unit == "projectile":
                # pick a weapon by name instead of typing an id
                ent = ttk.Combobox(self.body, state="readonly", width=30,
                                   values=[f"{PROJECTILES[i]}  ({i})" for i in range(NUM_PROJECTILES)])
                ent.current(v)
                ent.grid(row=r, column=1, columnspan=2, sticky="w", padx=4)
                ent.bind("<<ComboboxSelected>>", lambda ev, p=p, var=var, m=meaning, e=ent:
                         (var.set(str(e.current())), self.set_param(p, var, m, e)))
                stock = ttk.Label(self.body, text=PROJECTILES[p.stock], foreground="#888")
                stock.grid(row=r, column=4, sticky="w", padx=4)
                ttk.Button(self.body, text="Stock", width=6,
                           command=lambda p=p, var=var, m=meaning, e=ent: self.reset_param(p, var, m, e)).grid(row=r, column=5)
                r += 1
                continue
            ent = ttk.Entry(self.body, textvariable=var, width=10)
            ent.grid(row=r, column=1, sticky="w", padx=4)
            stock = ttk.Label(self.body, text=f"{p.stock}   (range {lo}–{hi})", foreground="#888")
            stock.grid(row=r, column=4, sticky="w", padx=4)
            ttk.Button(self.body, text="Set", width=4,
                       command=lambda p=p, var=var, m=meaning, e=ent: self.set_param(p, var, m, e)).grid(row=r, column=2)
            ttk.Button(self.body, text="Stock", width=6,
                       command=lambda p=p, var=var, m=meaning, e=ent: self.reset_param(p, var, m, e)).grid(row=r, column=5)
            ent.bind("<Return>", lambda ev, p=p, var=var, m=meaning, e=ent: self.set_param(p, var, m, e))
            self._mark(ent, v != p.stock)
            r += 1

        # attack tables
        self.tables = []          # [(table, {row: {attack: IntVar}}, {row: total label})]
        for ti, t in enumerate(b.attack_tables):
            ttk.Separator(self.body).grid(row=r, column=0, columnspan=6, sticky="ew", pady=10)
            r += 1
            ttk.Label(self.body, text=t.title, font="Heading").grid(row=r, column=0, sticky="w")
            ttk.Label(self.body, text=f"{t.desc} Each row must total {t.total}.", foreground="#666",
                      wraplength=px(700), justify="left").grid(row=r, column=1, columnspan=5, sticky="w")
            r += 1
            grid = ttk.Frame(self.body)
            grid.grid(row=r, column=0, columnspan=6, sticky="w", pady=4)
            names = list(t.attacks.values())
            ttk.Label(grid, text="row ↓   next attack →", foreground="#666").grid(row=0, column=0, padx=4)
            for c, n in enumerate(names):
                ttk.Label(grid, text=n, font="SmallBold").grid(row=0, column=c + 1, padx=6)
            ttk.Label(grid, text="total").grid(row=0, column=len(names) + 1, padx=6)
            weights = P.table_weights(g, t)
            vars_, totals = {}, {}
            for i, label in enumerate(t.rows):
                ttk.Label(grid, text=label, font="SmallBold").grid(row=i + 1, column=0, sticky="w", padx=4)
                vars_[label] = {}
                for c, n in enumerate(names):
                    var = tk.IntVar(value=weights[label].get(n, 0))
                    sp = ttk.Spinbox(grid, from_=0, to=t.total, width=4, textvariable=var,
                                     command=lambda ti=ti, l=label: self.update_total(ti, l))
                    sp.bind("<KeyRelease>", lambda e, ti=ti, l=label: self.update_total(ti, l))
                    sp.grid(row=i + 1, column=c + 1, padx=6, pady=2)
                    vars_[label][n] = var
                tl = ttk.Label(grid, text=str(t.total), width=4)
                tl.grid(row=i + 1, column=len(names) + 1)
                totals[label] = tl
            self.tables.append((t, vars_, totals))
            for label in t.rows:
                self.update_total(ti, label)
            r += 1
            btns = ttk.Frame(self.body)
            btns.grid(row=r, column=0, columnspan=6, sticky="w", pady=6)
            ttk.Button(btns, text="Apply", command=lambda ti=ti: self.apply_weights(ti)).pack(side="left")
            ttk.Button(btns, text="Stock", command=lambda ti=ti: self.stock_weights(ti)).pack(side="left", padx=6)
            r += 1

        if b.damage_class is not None:
            self.build_damage(r + 1)

    def build_damage(self, r):
        b, g = self.boss, self.app.g
        ttk.Separator(self.body).grid(row=r, column=0, columnspan=6, sticky="ew", pady=10)
        r += 1
        ttk.Label(self.body, text="Damage taken", font="Heading").grid(row=r, column=0, sticky="w")
        note = f"HP removed per hit, by weapon (damage class {b.damage_class}, 0–127)."
        if b.damage_shared_with:
            note += f" Shared with {b.damage_shared_with}: edits affect it too."
        ttk.Label(self.body, text=note, foreground="#666", wraplength=px(700)).grid(
            row=r, column=1, columnspan=5, sticky="w")
        r += 1
        grid = ttk.Frame(self.body)
        grid.grid(row=r, column=0, columnspan=6, sticky="w", pady=4)
        stock = P.get_damage(MMX1(P.STOCK_ROM), b.damage_class)
        cur = P.get_damage(g, b.damage_class)
        half = (NUM_PROJECTILES + 1) // 2
        self.damage_meanings = {}
        for i in range(NUM_PROJECTILES):
            col = 0 if i < half else 4
            row = i if i < half else i - half
            ttk.Label(grid, text=PROJECTILES[i]).grid(row=row, column=col, sticky="w", padx=(4, 6), pady=1)
            var = tk.StringVar(value=str(cur[i]))
            ent = ttk.Entry(grid, textvariable=var, width=5)
            ent.grid(row=row, column=col + 1, sticky="w")
            m = ttk.Label(grid, text="", width=22, foreground="#555")
            m.grid(row=row, column=col + 2, sticky="w", padx=(6, 24))
            self.damage_meanings[i] = (m, ent, stock[i])
            if cur[i] & 0x80:
                ent.configure(state="disabled")
            ent.bind("<Return>", lambda e, i=i, var=var: self.set_damage(i, var))
            ent.bind("<FocusOut>", lambda e, i=i, var=var: self.set_damage(i, var))
            self.describe_damage(i, cur[i])
        r += 1
        ttk.Button(self.body, text="Stock damage", command=self.stock_damage).grid(
            row=r, column=0, sticky="w", pady=6)

    def describe_damage(self, i, v):
        m, ent, stock = self.damage_meanings[i]
        hp = next((P.get(self.app.g, p) for p in self.boss.params if p.key == "max_hp"), 32)
        if v & 0x80:
            text = f"special handler (0x{v:02X})"
        elif v == 0:
            text = "no damage (0x00)"
        elif v >= hp:
            text = f"one-hit KO (0x{v:02X})"
        else:
            text = f"{v} HP (0x{v:02X})"
        if v != stock:
            text += f"  · stock {stock}"
        m.config(text=text)
        self._mark(ent, v != stock)

    def set_damage(self, i, var):
        cur = P.get_damage(self.app.g, self.boss.damage_class)[i]
        try:
            v = max(0, min(127, int(var.get().strip(), 10)))
        except ValueError:
            var.set(str(cur))
            return
        var.set(str(v))
        if v == cur:
            return
        try:
            P.set_damage(self.app.g, self.boss.damage_class, i, v)
        except P.ParamError as e:
            messagebox.showerror("Can't set damage", str(e))
            return
        self.describe_damage(i, v)
        self.app.changed(f"{self.boss.name}: {PROJECTILES[i]} damage = {v}")

    def stock_damage(self):
        stock = P.get_damage(MMX1(P.STOCK_ROM), self.boss.damage_class)
        for i, v in enumerate(stock):
            if not v & 0x80:
                P.set_damage(self.app.g, self.boss.damage_class, i, v)
        self.app.changed(f"{self.boss.name}: damage table reset to stock")
        self.show_boss()

    def _mark(self, entry, modified):
        if isinstance(entry, ttk.Entry) and not isinstance(entry, ttk.Combobox):
            entry.configure(style="Mod.TEntry" if modified else "TEntry")

    def set_param(self, p, var, meaning, entry):
        """Values are typed in base 10 and clamped to the parameter's range."""
        text = var.get().strip()
        try:
            v = P.clamp(p, int(text, 10))
        except ValueError:
            var.set(str(P.get(self.app.g, p)))   # not a number: put the current value back
            return
        var.set(str(v))
        try:
            P.put(self.app.g, p, v)
        except P.ParamError as e:
            messagebox.showerror("Can't set value", str(e))
            return
        meaning.config(text=P.describe(p, v))
        self._mark(entry, v != p.stock)
        self.app.changed(f"{self.boss.name}: {p.label} = {P.describe(p, v)}")

    def reset_param(self, p, var, meaning, entry):
        var.set(str(p.stock))
        if isinstance(entry, ttk.Combobox):
            entry.current(p.stock)
        self.set_param(p, var, meaning, entry)

    def update_total(self, ti, label):
        t, vars_, totals = self.tables[ti]
        total = 0
        for v in vars_[label].values():
            try:
                n = v.get()
            except tk.TclError:
                continue                      # mid-typing / empty: ignore until valid
            if n < 0 or n > t.total:
                n = max(0, min(t.total, n))
                v.set(n)
            total += n
        totals[label].config(text=str(total), foreground="black" if total == t.total else "red")

    def apply_weights(self, ti):
        t, vars_, _ = self.tables[ti]
        try:
            for label, row in vars_.items():
                P.set_weights(self.app.g, t, label, {n: v.get() for n, v in row.items()})
        except (P.ParamError, tk.TclError) as e:
            messagebox.showerror("Can't apply pattern", str(e))
            return
        self.app.changed(f"{self.boss.name}: {t.title.lower()} updated")

    def stock_weights(self, ti):
        t, vars_, _ = self.tables[ti]
        w = P.table_weights(MMX1(P.STOCK_ROM), t)
        for label, row in vars_.items():
            for n, v in row.items():
                v.set(w[label].get(n, 0))
            self.update_total(ti, label)
        self.apply_weights(ti)


# ---------------------------------------------------------------------------------------
class EnemyTab(ttk.Frame):
    COLS = ("id", "name", "hp", "states", "routine", "levels")

    def __init__(self, parent, app: App):
        super().__init__(parent, padding=8)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Show stage:").pack(side="left")
        self.level_filter = ttk.Combobox(top, state="readonly", width=22,
                                         values=["All stages"] + LEVEL_NAMES)
        self.level_filter.current(0)
        self.level_filter.pack(side="left", padx=6)
        self.level_filter.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(top, text="Double-click a row to edit. Names are your own labels (saved in labels.json).",
                  foreground="#666").pack(side="left", padx=12)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=6)
        tf = ttk.Frame(body)
        self.tree = ttk.Treeview(tf, columns=self.COLS, show="headings", selectmode="browse")
        widths = dict(id=50, name=230, hp=60, states=60, routine=90, levels=420)
        for c in self.COLS:
            self.tree.heading(c, text=c.upper() if c in ("id", "hp") else c.title(),
                              command=lambda c=c: self.sort_by(c))
            # columns keep a usable width; a narrow window scrolls sideways instead of squashing them
            self.tree.column(c, width=px(widths[c]), minwidth=px(min(widths[c], 200)),
                             anchor="w" if c in ("name", "levels") else "center")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        side_scroll = ScrollFrame(body, track_width=True, padding=(12, 0, 0, 0))
        side_scroll.pack(side="right", fill="y")      # packed first so the wide table can't push it off screen
        tf.pack(side="left", fill="both", expand=True)
        side = side_scroll.body
        self.detail = ttk.Label(side, text="", justify="left", wraplength=px(260))
        self.detail.pack(anchor="w")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        ttk.Button(side, text="Edit…", command=self.edit_selected).pack(anchor="w", pady=(10, 2))
        ttk.Button(side, text="View code", command=self.view_code).pack(anchor="w", pady=2)
        self.sprite_label = ttk.Label(side)
        self.sprite_label.pack(anchor="w", pady=(12, 0))
        self.sprite_note = ttk.Label(side, foreground="#888", wraplength=px(260), justify="left")
        self.sprite_note.pack(anchor="w")
        self.sprite_photo = None
        self.sprites = None
        self.sort_col, self.sort_rev = "id", False

    def rows(self):
        labels = P.load_labels()
        lf = self.level_filter.current() - 1
        for i, r, n, hp, lv in P.enemy_catalogue():
            if lf >= 0 and lf not in lv:
                continue
            yield dict(id=i, name=labels.get(f"{i:02X}", ""), hp=P.get(self.app.g, hp) if hp else None,
                       hp_param=hp, states=n, routine=r, levels=lv)

    def refresh(self):
        self.sprites = SpriteRenderer(self.app.g)
        self.data = {d["id"]: d for d in self.rows()}
        self.redraw()

    def redraw(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        key = {"id": lambda d: d["id"], "name": lambda d: (d["name"] == "", d["name"]),
               "hp": lambda d: -1 if d["hp"] is None else d["hp"], "states": lambda d: d["states"],
               "routine": lambda d: d["routine"], "levels": lambda d: len(d["levels"])}[self.sort_col]
        for d in sorted(self.data.values(), key=key, reverse=self.sort_rev):
            hp = "" if d["hp"] is None else d["hp"]
            if d["hp_param"] and d["hp"] != d["hp_param"].stock:
                hp = f"{hp} *"
            self.tree.insert("", "end", iid=str(d["id"]), values=(
                f"{d['id']:02X}", d["name"], hp, d["states"], f"${d['routine']:06X}",
                ", ".join(LEVEL_NAMES[x] for x in d["levels"])))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])

    def sort_by(self, col):
        self.sort_rev = not self.sort_rev if self.sort_col == col else False
        self.sort_col = col
        self.redraw()

    def selected(self):
        s = self.tree.selection()
        return self.data[int(s[0])] if s else None

    def show_detail(self):
        d = self.selected()
        if not d:
            return
        hp = d["hp_param"]
        txt = [f"Object {d['id']:02X}  {d['name'] or '(unnamed)'}",
               f"Code ${d['routine']:06X}, {d['states']} top-level states",
               f"HP: {d['hp'] if d['hp'] is not None else 'not found automatically'}"
               + (f" (stock {hp.stock}) at ${hp.addr:06X}" if hp else ""),
               "Placed in: " + (", ".join(LEVEL_NAMES[x] for x in d["levels"]) or "no stage events")]
        self.detail.config(text="\n\n".join(txt))
        self.show_sprite(d["id"])

    def show_sprite(self, obj_id):
        img = self.sprites.render(obj_id, scale=3) if self.sprites else None
        if img is None:
            self.sprite_photo = None
            self.sprite_label.config(image="")
            self.sprite_note.config(text="No sprite found for this object.")
            return
        img.thumbnail((260, 260))
        bg = Image.new("RGBA", (img.width + 16, img.height + 16), (40, 40, 48, 255))
        bg.alpha_composite(img, (8, 8))
        self.sprite_photo = photo(bg)
        self.sprite_label.config(image=self.sprite_photo)
        self.sprite_note.config(text="First frame of its sprite set (usually the idle pose).")

    def edit_selected(self):
        d = self.selected()
        if not d:
            return
        win = tk.Toplevel(self)
        win.title(f"Object {d['id']:02X}")
        win.transient(self)
        f = ttk.Frame(win, padding=12)
        f.pack()
        ttk.Label(f, text="Name").grid(row=0, column=0, sticky="w")
        name = tk.StringVar(value=d["name"])
        ttk.Entry(f, textvariable=name, width=30).grid(row=0, column=1, pady=4)
        hpv = tk.StringVar(value="" if d["hp"] is None else str(d["hp"]))
        ttk.Label(f, text="HP").grid(row=1, column=0, sticky="w")
        hp_entry = ttk.Entry(f, textvariable=hpv, width=8, state="normal" if d["hp_param"] else "disabled")
        hp_entry.grid(row=1, column=1, sticky="w", pady=4)

        def ok():
            P.save_label(d["id"], name.get().strip())
            if d["hp_param"] and hpv.get() != str(d["hp"]):
                try:
                    v = P.clamp(d["hp_param"], int(hpv.get().strip(), 10))
                    P.put(self.app.g, d["hp_param"], v)
                    self.app.changed(f"Object {d['id']:02X} HP = {v}")
                except (ValueError, P.ParamError) as e:
                    messagebox.showerror("Can't set HP", str(e), parent=win)
                    return
            win.destroy()
            self.refresh()
            self.show_detail()

        ttk.Button(f, text="OK", command=ok).grid(row=2, column=1, sticky="e", pady=(8, 0))
        win.bind("<Return>", lambda e: ok())

    def view_code(self):
        d = self.selected()
        if d:
            self.app.code_tab.show(d["routine"])


# ---------------------------------------------------------------------------------------
class LevelTab(ttk.Frame):
    """Stage map + editable event list (enemies, items, triggers)."""
    COLORS = {0: "#ffd400", 1: "#22d3ee", 2: "#4ade80", 3: "#f43f5e"}
    TYPE_NAMES = ["0 item / door", "1 script", "2 trigger", "3 enemy"]

    def __init__(self, parent, app: App):
        super().__init__(parent, padding=8)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.level = ttk.Combobox(top, state="readonly", width=22, values=LEVEL_NAMES)
        self.level.current(8)
        self.level.pack(side="left")
        self.level.bind("<<ComboboxSelected>>", lambda e: self.load_level())
        self.opts = {}
        for key, label in (("events", "Event markers"), ("locks", "Camera locks"), ("collision", "Collision")):
            v = tk.BooleanVar(value=key == "events")
            ttk.Checkbutton(top, text=label, variable=v,
                            command=self.draw_markers if key == "events" else self.draw).pack(side="left", padx=6)
            self.opts[key] = v
        ttk.Label(top, text="Zoom").pack(side="left", padx=(12, 2))
        self.zoom = ttk.Combobox(top, state="readonly", width=5, values=["25%", "50%", "100%"])
        self.zoom.current(1)
        self.zoom.pack(side="left")
        self.zoom.bind("<<ComboboxSelected>>", lambda e: self.draw())
        self.info = ttk.Label(top, foreground="#666")
        self.info.pack(side="left", padx=12)

        pan = ttk.PanedWindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True, pady=6)
        cf = ttk.Frame(pan)
        self.canvas = tk.Canvas(cf, background="#222", highlightthickness=0)
        hs = ttk.Scrollbar(cf, orient="horizontal", command=self.canvas.xview)
        vs = ttk.Scrollbar(cf, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hs.set, yscrollcommand=vs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        cf.rowconfigure(0, weight=1)
        cf.columnconfigure(0, weight=1)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<Double-Button-1>", self.on_double)
        for seq in ("<Button-2>", "<Button-3>") if MAC else ("<Button-3>",):   # right-click
            self.canvas.bind(seq, self.on_right)
        pan.add(cf, weight=3)

        side_nb = ttk.Notebook(pan)
        events_page, gfx_page = ScrollFrame(side_nb, track_width=True), ScrollFrame(side_nb, track_width=True)
        side_nb.add(events_page, text="Events")
        side_nb.add(gfx_page, text="Enemy graphics")
        side = events_page.body
        side.configure(padding=4)
        self.gfx_page = gfx_page.body
        self.gfx_page.configure(padding=4)
        self.side_nb = side_nb
        side_nb.bind("<<NotebookTabChanged>>", lambda e: self.on_side_tab())
        lf = ttk.Frame(side)
        lf.pack(fill="both", expand=True)
        cols = ("x", "y", "kind", "id", "what")
        self.events = ttk.Treeview(lf, columns=cols, show="headings", selectmode="browse", height=8)
        for c, w in zip(cols, (50, 50, 60, 55, 160)):
            self.events.heading(c, text=c.title())
            self.events.column(c, width=px(w), anchor="w")
        es = ttk.Scrollbar(lf, orient="vertical", command=self.events.yview)
        self.events.configure(yscrollcommand=es.set)
        self.events.pack(side="left", fill="both", expand=True)
        es.pack(side="left", fill="y")
        self.events.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.build_editor(side)
        self.build_gfx_panel(self.gfx_page)
        pan.add(side_nb, weight=1)

        self.photo = None
        self.cache = {}
        self.marker = None
        self.work = []          # editable copy of the current stage's events
        self.sprite_photo = None

    # --- editor panel --------------------------------------------------------------------
    def build_editor(self, parent):
        f = ttk.LabelFrame(parent, text="Selected event", padding=8)
        f.pack(fill="x", pady=(8, 0))
        self.ed = {}
        ttk.Label(f, text="Type").grid(row=0, column=0, sticky="w")
        self.ed["type"] = ttk.Combobox(f, state="readonly", width=16, values=self.TYPE_NAMES)
        self.ed["type"].grid(row=0, column=1, columnspan=2, sticky="w", pady=2)
        self.ed["type"].bind("<<ComboboxSelected>>", lambda e: self.fill_object_choices())
        ttk.Label(f, text="Object").grid(row=1, column=0, sticky="w")
        self.ed["id"] = ttk.Combobox(f, width=30)
        self.ed["id"].grid(row=1, column=1, columnspan=2, sticky="w", pady=2)
        self.hex_labels = {}
        for r, (key, label, hi) in enumerate((("sub", "Sub-id", 255), ("x", "X", 0x1FFF), ("y", "Y", 0xFFFF)), 2):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w")
            var = tk.StringVar()
            e = ttk.Entry(f, textvariable=var, width=8)
            e.grid(row=r, column=1, sticky="w", pady=2)
            e.bind("<Return>", lambda ev: self.apply())
            hl = ttk.Label(f, foreground="#888")
            hl.grid(row=r, column=2, sticky="w", padx=6)
            var.trace_add("write", lambda *a, k=key, v=var, h=hi: self.show_hex(k, v, h))
            self.ed[key] = var
            self.hex_labels[key] = hl
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(b, text="Apply", command=self.apply).pack(side="left")
        ttk.Button(b, text="Add copy", command=self.add_copy).pack(side="left", padx=4)
        ttk.Button(b, text="Delete", command=self.delete).pack(side="left")
        ttk.Button(b, text="Revert stage", command=self.revert).pack(side="left", padx=4)
        self.space = ttk.Label(f, foreground="#555")
        self.space.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(f, text="Double-click the map to move the selected event there. Values are base 10.",
                  foreground="#888", wraplength=px(300), justify="left").grid(row=7, column=0, columnspan=3, sticky="w")
        self.auto_gfx = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Automatically load graphics for enemies I place", variable=self.auto_gfx).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.gfx_warn = ttk.Label(f, foreground="#b45309", wraplength=px(300), justify="left")
        self.gfx_warn.grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.gfx_fix = ttk.Button(f, text="Add its graphics to that set…", command=self.fix_graphics)
        self.ed_sprite = ttk.Label(f)
        self.ed_sprite.grid(row=10, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def show_hex(self, key, var, hi):
        try:
            v = int(var.get().strip(), 10)
            self.hex_labels[key].config(text=f"0x{max(0, min(hi, v)):X}")
        except ValueError:
            self.hex_labels[key].config(text="")

    def fill_object_choices(self):
        t = self.ed["type"].current()
        if t == 3:
            labels = P.load_labels()
            vals = [f"{i:02X}  {labels.get(f'{i:02X}', '')}".rstrip() for i in range(1, 0x6C)]
        else:
            vals = [f"{i:02X}" for i in range(0x100)]
        self.ed["id"].config(values=vals)

    # --- data ----------------------------------------------------------------------------
    def refresh(self):
        self.cache.clear()
        self.sprites = SpriteRenderer(self.app.g)
        self.load_level()

    def load_level(self):
        self.work = [e.copy() for e in self.app.g.events(self.level.current())]
        self.draw()

    def describe(self, e, labels):
        if e.type == 3:
            return labels.get(f"{e.id:02X}", "")
        if e.type == 2 and e.id == 0:
            return f"camera lock {e.sub:X}"
        if e.type == 2 and e.id in (0x2, 0xB):
            return f"checkpoint {e.sub & 0xF}"
        if e.type == 2 and e.id in (0x15, 0x18):
            return "load enemy graphics"
        if e.type == 0 and e.id == 7:
            return "boss door"
        return ""

    def fill_list(self, select=None):
        labels = P.load_labels()
        self.events.delete(*self.events.get_children())
        for n, e in enumerate(self.work):
            self.events.insert("", "end", iid=str(n), values=(
                e.x, e.y, ["item", "script", "trigger", "enemy"][e.type], f"{e.id:02X}.{e.sub:02X}",
                self.describe(e, labels)))
        g, L = self.app.g, self.level.current()
        self.space.config(text=f"Event space: {g.events_size(L)} / {g.events_capacity(L)} bytes"
                               + ("" if g.expanded else "  (stock ROM: can't grow — use Expand ROM)"))
        if select is not None and self.events.exists(str(select)):
            self.events.selection_set(str(select))
            self.events.see(str(select))

    def selected_index(self):
        s = self.events.selection()
        return int(s[0]) if s else None

    def on_select(self):
        i = self.selected_index()
        if i is None:
            return
        e = self.work[i]
        self.ed["type"].current(e.type)
        self.fill_object_choices()
        labels = P.load_labels()
        name = labels.get(f"{e.id:02X}", "") if e.type == 3 else ""
        self.ed["id"].set(f"{e.id:02X}  {name}".rstrip())
        self.ed["sub"].set(str(e.sub))
        self.ed["x"].set(str(e.x))
        self.ed["y"].set(str(e.y))
        self.focus_event(e)
        self.check_graphics(e)
        img = self.sprites.render(e.id, scale=2) if e.type == 3 else None
        if img:
            img.thumbnail((180, 180))
            self.sprite_photo = photo(img)
            self.ed_sprite.config(image=self.sprite_photo)
        else:
            self.sprite_photo = None
            self.ed_sprite.config(image="")

    def read_editor(self, e):
        """Copy editor fields into event e (clamped). Returns False if a field isn't a number."""
        def num_(key, hi):
            return max(0, min(hi, int(self.ed[key].get().strip(), 10)))
        try:
            e.type = self.ed["type"].current()
            e.id = max(0, min(0xFF, int(self.ed["id"].get().split()[0], 16)))
            e.sub = num_("sub", 0xFF)
            e.x = num_("x", 0x1FFF)
            e.y = num_("y", 0xFFFF)
        except (ValueError, IndexError):
            messagebox.showerror("Invalid value", "Object is a hex id (e.g. 2D); sub-id, X and Y are base-10 numbers.")
            return False
        e.block = min(e.x >> 5, 0xFF)      # the game loads events by column: column = X / 32
        return True

    def commit(self, new_work, select=None, msg=""):
        """Write the edited list into the ROM (in memory); refuse if it doesn't fit."""
        g, L = self.app.g, self.level.current()
        ordered = sorted(new_work, key=lambda e: e.block)        # stable: keeps order within a column
        try:
            g.write_events(L, ordered)
        except ValueError as err:
            messagebox.showerror("Doesn't fit", str(err))
            return False
        self.work = [e.copy() for e in g.events(L)]
        if select is not None:
            target = ordered[select] if isinstance(select, int) else select
            select = next((n for n, e in enumerate(self.work)
                           if (e.type, e.id, e.sub, e.x, e.y) == (target.type, target.id, target.sub, target.x, target.y)), None)
        self.fill_list(select)
        self.draw_markers()
        if select is not None and self.auto_gfx.get() and select < len(self.work):
            e = self.work[select]
            if e.type == 3:
                gfx = G.sprite_ids(g, e.id)[1]
                sec = self.section_at(e.x)
                if all(x.gfx != gfx for x in G.read_set(g, L, sec.set_no)):
                    self.load_graphics(sec, gfx, quiet=True)
        self.fill_sets()
        if select is not None:
            self.on_select()
        self.app.changed(msg)
        return True

    def apply(self):
        i = self.selected_index()
        if i is None:
            return
        work = [e.copy() for e in self.work]
        if not self.read_editor(work[i]):
            return
        self.commit(work, work[i], f"{LEVEL_NAMES[self.level.current()]}: event updated")

    def add_copy(self):
        i = self.selected_index()
        if i is None:
            return
        work = [e.copy() for e in self.work]
        new = work[i].copy()
        if not self.read_editor(new):
            return
        new.x = min(0x1FFF, new.x + 32)
        new.block = min(new.x >> 5, 0xFF)
        work.append(new)
        self.commit(work, new, f"{LEVEL_NAMES[self.level.current()]}: event added")

    def delete(self):
        i = self.selected_index()
        if i is None:
            return
        work = [e for n, e in enumerate(self.work) if n != i]
        if self.commit(work, None, f"{LEVEL_NAMES[self.level.current()]}: event deleted"):
            self.marker = None

    def revert(self):
        L = self.level.current()
        stock = MMX1(P.STOCK_ROM)
        if not messagebox.askyesno("Revert stage", f"Put {LEVEL_NAMES[L]}'s events back to the original ROM's?"):
            return
        evs = stock.events(L)
        self.commit(evs, None, f"{LEVEL_NAMES[L]}: events reverted")

    # --- graphics warning in the event editor ---------------------------------------------
    def check_graphics(self, e):
        self.gfx_fix.grid_forget()
        self.gfx_warn.config(text="")
        self.fix_target = None
        if e.type != 3:
            return
        g, L = self.app.g, self.level.current()
        gfx = G.sprite_ids(g, e.id)[1]
        sec = self.section_at(e.x)
        if any(x.gfx == gfx for x in G.read_set(g, L, sec.set_no)):
            self.gfx_warn.config(text=f"✓ This enemy's graphics are loaded in this section "
                                      f"(X {sec.start}–{sec.end}).", foreground="#15803d")
            return
        self.gfx_warn.config(text=f"⚠ This enemy's graphics aren't loaded in this section (X {sec.start}–{sec.end}), "
                                  f"so it will show garbage.", foreground="#b45309")
        self.fix_target = (sec, gfx)
        self.gfx_fix.config(text="Load its graphics in this section")
        self.gfx_fix.grid(row=9, column=0, columnspan=3, sticky="w")

    def fix_graphics(self):
        if self.fix_target:
            sec, gfx = self.fix_target
            self.load_graphics(sec, gfx)

    def load_graphics(self, sec, gfx, quiet=False):
        """Add graphics `gfx` to a section's set (automatic VRAM / palette / slot)."""
        g, L = self.app.g, self.level.current()
        try:
            msg = G.add_graphics(g, L, sec.set_no, gfx, self.known_pal)
        except ValueError as err:
            if not quiet:
                messagebox.showerror("Can't load graphics here", str(err))
            else:
                self.app.set_status(f"⚠ {err}")
            return False
        self.app.changed(f"{LEVEL_NAMES[L]}, X {sec.start}–{sec.end}: {msg}")
        self.fill_sets()
        i = self.selected_index()
        if i is not None:
            self.check_graphics(self.work[i])
        return True

    def on_side_tab(self):
        if self.side_nb.index("current") == 1:
            sec = self.current_section()
            if sec:
                self.highlight_section(sec)
        else:
            self.canvas.delete("sec")

    def section_at(self, x):
        secs = G.sections(self.app.g, self.level.current(), self.work)
        return next((s for s in secs if s.start <= x < s.end), secs[-1])

    # --- enemy graphics panel ----------------------------------------------------------------
    def build_gfx_panel(self, parent):
        ttk.Label(parent, text="The stage is split into sections; each section loads graphics for a few "
                               "enemy types. An enemy only looks right in a section that loads its graphics.",
                  foreground="#666", wraplength=px(330), justify="left").pack(anchor="w")
        ttk.Label(parent, text="Section", font="Bold").pack(anchor="w", pady=(6, 0))
        self.sec_list = tk.Listbox(parent, height=7, exportselection=False, font="MonoSmall")
        self.sec_list.pack(fill="x", pady=2)
        self.sec_list.bind("<<ListboxSelect>>", lambda e: self.show_section())

        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(8, 2))
        ttk.Label(head, text="Enemies loaded here", font="Bold").pack(side="left")
        ttk.Button(head, text="+ Add enemy…", command=self.pick_enemy).pack(side="right")
        self.cards = ttk.Frame(parent)
        self.cards.pack(fill="x")
        self.meter_space = ttk.Label(parent)
        self.meter_space.pack(anchor="w", pady=(6, 0))
        self.meter_bar = tk.Canvas(parent, height=10, background="#e5e7eb", highlightthickness=0)
        self.meter_bar.pack(fill="x")
        self.meter_slots = ttk.Label(parent)
        self.meter_slots.pack(anchor="w", pady=(2, 0))
        self.gfx_problems = ttk.Label(parent, foreground="#b91c1c", wraplength=px(330), justify="left")
        self.gfx_problems.pack(anchor="w")
        b = ttk.Frame(parent)
        b.pack(fill="x", pady=(6, 0))
        ttk.Button(b, text="Reset section to original", command=self.reset_section).pack(side="left")
        self.adv_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(b, text="Advanced", variable=self.adv_on, command=self.toggle_advanced).pack(side="right")
        self.gfx_space = ttk.Label(parent, foreground="#888")
        self.gfx_space.pack(anchor="w", pady=(4, 0))
        self.adv = ttk.LabelFrame(parent, text="Advanced: raw set entries", padding=6)
        self.build_advanced(self.adv)
        self.card_photos = []
        self.known_pal = G.known_palettes(MMX1(P.STOCK_ROM))
        self.sec_rows = []

    def build_advanced(self, f):
        self.adv_tree = ttk.Treeview(f, columns=("gfx", "vram", "pal", "slot"), show="headings", height=4,
                                     selectmode="browse")
        for c, w, t in (("gfx", 50, "Gfx"), ("vram", 100, "VRAM"), ("pal", 50, "Palette"), ("slot", 50, "Slot")):
            self.adv_tree.heading(c, text=t)
            self.adv_tree.column(c, width=px(w), anchor="w")
        self.adv_tree.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.adv_tree.bind("<<TreeviewSelect>>", lambda e: self.adv_show())
        self.adv_vars = {}
        for r, (k, label) in enumerate((("gfx", "Graphics"), ("vram", "VRAM"), ("pal", "Palette"), ("slot", "Slot")), 1):
            ttk.Label(f, text=f"{label} (hex)").grid(row=r, column=0, sticky="w")
            v = tk.StringVar()
            ttk.Entry(f, textvariable=v, width=8).grid(row=r, column=1, sticky="w", pady=1)
            self.adv_vars[k] = v
        bb = ttk.Frame(f)
        bb.grid(row=5, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Button(bb, text="Apply", command=lambda: self.adv_edit("apply")).pack(side="left")
        ttk.Button(bb, text="Add", command=lambda: self.adv_edit("add")).pack(side="left", padx=4)

    def toggle_advanced(self):
        if self.adv_on.get():
            self.adv.pack(fill="x", pady=(6, 0))
        else:
            self.adv.pack_forget()

    def current_section(self):
        s = self.sec_list.curselection()
        return self.sec_rows[s[0]] if s and s[0] < len(self.sec_rows) else None

    def fill_sets(self):
        g, L = self.app.g, self.level.current()
        self.users = G.gfx_users(g)
        sel = self.sec_list.curselection()
        self.sec_list.delete(0, "end")
        self.sec_rows = []
        for sec in G.sections(g, L, self.work):
            self.sec_rows.append(sec)
            self.sec_list.insert("end", f"X {sec.start:>5} – {sec.end:<5}  ({sec.how})")
        for n, why in G.other_sets(g, L, self.work):
            self.sec_rows.append(G.Section(-1, -1, n, why))
            self.sec_list.insert("end", f"other: set {n} ({why})")
        self.sec_list.selection_set(sel[0] if sel and sel[0] < len(self.sec_rows) else 0)
        self.gfx_space.config(text=f"Room left for grown sections (bank $86): {G.free_bytes(g)} bytes")
        self.show_section()

    def show_section(self):
        sec = self.current_section()
        if sec is None:
            return
        g, L = self.app.g, self.level.current()
        entries = G.read_set(g, L, sec.set_no)
        labels = P.load_labels()
        for w in self.cards.winfo_children():
            w.destroy()
        self.card_photos = []
        for k, e in enumerate(entries):
            row = ttk.Frame(self.cards, padding=(0, 2))
            row.pack(fill="x")
            ids = self.users.get(e.gfx, [])
            img = self.sprites.render(ids[0], scale=1) if ids else None
            if img:
                img.thumbnail((44, 44))
                ph = photo(img)
                self.card_photos.append(ph)
                ttk.Label(row, image=ph, width=6).pack(side="left")
            else:
                ttk.Label(row, text="  ?  ", width=6, foreground="#999").pack(side="left")
            names = ", ".join(f"{i:02X} {labels.get(f'{i:02X}', '')}".strip() for i in ids[:2]) or \
                "not an enemy type (props / effects?)"
            share = 100 * G.gfx_words(g, e.gfx) / (G.VRAM_LIMIT - 0x0400) if e.vram else 0
            ttk.Label(row, text=f"{names}\n{share:.0f}% of graphics space", justify="left").pack(side="left", padx=4)
            ttk.Button(row, text="Remove", width=7,
                       command=lambda k=k: self.remove_entry(k)).pack(side="right")
        used, avail = G.vram_use(g, entries)
        pct = min(100, 100 * used / avail)
        self.meter_space.config(text=f"Graphics space: {pct:.0f}% used")
        self.meter_bar.delete("all")
        self.meter_bar.update_idletasks()
        W = max(self.meter_bar.winfo_width(), 300)
        self.meter_bar.create_rectangle(0, 0, W * pct / 100, 10, fill="#ef4444" if pct > 90 else "#3b82f6", width=0)
        slots = len({e.slot for e in entries})
        self.meter_slots.config(text=f"Palette slots: {slots} of 4 used")
        probs = G.problems(g, entries)
        self.gfx_problems.config(text="\n".join("⚠ " + p for p in probs))
        if self.side_nb.index("current") == 1:
            self.highlight_section(sec)
        self.adv_fill(entries)

    def highlight_section(self, sec):
        self.canvas.delete("sec")
        if sec.start < 0 or not self.photo:
            return
        k = self.scale()
        H = self.photo.height()
        self.canvas.create_rectangle(sec.start * k, 0, sec.end * k, H, outline="#facc15", width=3, tags="sec")
        self.canvas.create_text(sec.start * k + 6, 6, text=f"section X {sec.start}–{sec.end}", anchor="nw",
                                fill="#facc15", font="Bold", tags="sec")

    def remove_entry(self, k):
        sec = self.current_section()
        g, L = self.app.g, self.level.current()
        entries = G.read_set(g, L, sec.set_no)
        gone = entries.pop(k)
        users = [e for e in self.work if e.type == 3 and G.sprite_ids(g, e.id)[1] == gone.gfx
                 and sec.start <= e.x < sec.end]
        if users and not messagebox.askyesno("Remove graphics",
                                             f"{len(users)} enemy placement(s) in this section use these graphics "
                                             "and will show garbage. Remove anyway?"):
            return
        G.write_set(g, L, sec.set_no, entries)
        self.app.changed(f"{LEVEL_NAMES[L]}: removed graphics {gone.gfx:02X} from section X {sec.start}–{sec.end}")
        self.fill_sets()

    def reset_section(self):
        sec = self.current_section()
        if sec is None:
            return
        g, L = self.app.g, self.level.current()
        G.write_set(g, L, sec.set_no, G.read_set(MMX1(P.STOCK_ROM), L, sec.set_no))
        self.app.changed(f"{LEVEL_NAMES[L]}: section graphics reset to original")
        self.fill_sets()

    def pick_enemy(self):
        sec = self.current_section()
        if sec is None:
            return
        win = tk.Toplevel(self)
        win.title("Add enemy graphics to this section")
        win.geometry(f"{min(760, self.winfo_screenwidth() - 40)}x{min(560, self.winfo_screenheight() - 100)}")
        ttk.Label(win, text="Click an enemy to load its graphics in this section.", padding=6).pack(anchor="w")
        cv = tk.Canvas(win, background="#2a2a33", highlightthickness=0)
        sb = ttk.Scrollbar(win, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        labels = P.load_labels()
        loaded = {e.gfx for e in G.read_set(self.app.g, self.level.current(), sec.set_no)}
        self.pick_photos = []
        cell, cols = 120, 6
        n = 0
        for i in range(1, 0x6C):
            img = self.sprites.render(i, scale=2)
            if img is None:
                continue
            gfx = G.sprite_ids(self.app.g, i)[1]
            img.thumbnail((cell - 20, cell - 36))
            ph = photo(img)
            self.pick_photos.append(ph)
            x, y = (n % cols) * cell, (n // cols) * cell
            tag = f"e{i}"
            cv.create_rectangle(x + 4, y + 4, x + cell - 4, y + cell - 4, outline="#444",
                                fill="#1f2937" if gfx not in loaded else "#14532d", tags=tag)
            cv.create_image(x + cell // 2, y + (cell - 24) // 2 + 4, image=ph, tags=tag)
            name = labels.get(f"{i:02X}", "")
            cv.create_text(x + cell // 2, y + cell - 14, text=f"{i:02X} {name}"[:18] + (" ✓" if gfx in loaded else ""),
                           fill="#e5e7eb", font="Small", tags=tag)
            cv.tag_bind(tag, "<Button-1>", lambda e, gfx=gfx, win=win: (win.destroy(), self.load_graphics(sec, gfx)))
            n += 1
        cv.configure(scrollregion=(0, 0, cols * cell, ((n + cols - 1) // cols) * cell))
        bind_wheel(cv, cv, cv.winfo_exists)

    # advanced raw editing
    def adv_fill(self, entries):
        self.adv_tree.delete(*self.adv_tree.get_children())
        for k, e in enumerate(entries):
            self.adv_tree.insert("", "end", iid=str(k), values=(f"{e.gfx:02X}", f"{e.vram:04X}", f"{e.pal:02X}", f"{e.slot:02X}"))

    def adv_show(self):
        s = self.adv_tree.selection()
        sec = self.current_section()
        if not s or sec is None:
            return
        e = G.read_set(self.app.g, self.level.current(), sec.set_no)[int(s[0])]
        for k, v in (("gfx", f"{e.gfx:02X}"), ("vram", f"{e.vram:04X}"), ("pal", f"{e.pal:02X}"), ("slot", f"{e.slot:02X}")):
            self.adv_vars[k].set(v)

    def adv_edit(self, action):
        sec = self.current_section()
        if sec is None:
            return
        g, L = self.app.g, self.level.current()
        entries = G.read_set(g, L, sec.set_no)
        try:
            e = G.Entry(*(int(self.adv_vars[k].get(), 16) for k in ("gfx", "vram", "pal", "slot")))
        except ValueError:
            messagebox.showerror("Invalid entry", "All four fields are hex values.")
            return
        s = self.adv_tree.selection()
        if action == "apply":
            if not s:
                return
            entries[int(s[0])] = e
        else:
            entries.append(e)
        probs = G.problems(g, entries)
        if probs and not messagebox.askyesno("Possible problems", "\n".join(probs) + "\n\nWrite it anyway?"):
            return
        try:
            G.write_set(g, L, sec.set_no, entries)
        except ValueError as err:
            messagebox.showerror("Can't write set", str(err))
            return
        self.app.changed(f"{LEVEL_NAMES[L]}: section X {sec.start}–{sec.end} graphics edited")
        self.fill_sets()

    # --- map -----------------------------------------------------------------------------
    def scale(self):
        return {0: 0.25, 1: 0.5, 2: 1.0}[self.zoom.current()]

    def draw(self):
        L = self.level.current()
        key = (L, self.opts["locks"].get(), self.opts["collision"].get(), self.zoom.current())
        self.app.set_status(f"Rendering {LEVEL_NAMES[L]}…")
        self.update_idletasks()
        if key not in self.cache:
            img = render(self.app.g, L, 0, events=False,
                         collision=self.opts["collision"].get(), locks=self.opts["locks"].get())
            s = self.scale()
            if s != 1:
                img = img.resize((int(img.width * s), int(img.height * s)))
            self.cache[key] = img
        img = self.cache[key]
        self.photo = photo(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, img.width, img.height))
        g = self.app.g
        w, h, used, _ = g.layout(L)
        self.info.config(text=f"{w}×{h} scenes · {g.num_checkpoints(L)} checkpoints")
        self.fill_list()
        self.draw_markers()
        self.fill_sets()
        self.app.set_status(f"{LEVEL_NAMES[L]} ready. Drag to pan; click a marker to select it.")

    def draw_markers(self):
        self.canvas.delete("ev")
        self.marker = None
        if not self.opts["events"].get():
            return
        k = self.scale()
        for n, e in enumerate(self.work):
            x, y = e.x * k, e.y * k
            r = max(4, 8 * k)
            c = self.COLORS[e.type]
            self.canvas.create_rectangle(x - r, y - r, x + r, y + r, outline=c, width=2, tags=("ev", f"ev{n}"))
            if k >= 0.5:
                self.canvas.create_text(x + r + 2, y - r, text=f"{e.id:02X}", fill=c, anchor="nw",
                                        font="MonoTiny", tags=("ev", f"ev{n}"))
        i = self.selected_index()
        if i is not None and i < len(self.work):
            self.focus_event(self.work[i], scroll=False)

    def on_press(self, ev):
        self.canvas.scan_mark(ev.x, ev.y)
        cx, cy = self.canvas.canvasx(ev.x), self.canvas.canvasy(ev.y)
        for item in self.canvas.find_overlapping(cx - 2, cy - 2, cx + 2, cy + 2):
            for t in self.canvas.gettags(item):
                if t.startswith("ev") and t[2:].isdigit():
                    self.events.selection_set(t[2:])
                    self.events.see(t[2:])
                    return

    def on_double(self, ev):
        i = self.selected_index()
        if i is None:
            return
        k = self.scale()
        x = int(self.canvas.canvasx(ev.x) / k)
        y = int(self.canvas.canvasy(ev.y) / k)
        self.ed["x"].set(str(max(0, min(0x1FFF, x))))
        self.ed["y"].set(str(max(0, min(0xFFFF, y))))
        self.apply()

    def on_right(self, ev):
        k = self.scale()
        x = int(self.canvas.canvasx(ev.x) / k)
        y = int(self.canvas.canvasy(ev.y) / k)
        L = self.level.current()
        m = tk.Menu(self, tearoff=0)
        m.add_command(label=f"Test here ({x}, {y})", command=lambda: self.app.run_test(L, x, y))
        m.add_command(label=f"Test here, landing on the floor below x={x}",
                      command=lambda: self.app.run_test(L, x))
        m.tk_popup(ev.x_root, ev.y_root)

    def focus_event(self, e, scroll=True):
        k = self.scale()
        x, y = e.x * k, e.y * k
        if self.marker:
            self.canvas.delete(self.marker)
        self.marker = self.canvas.create_oval(x - 14, y - 14, x + 14, y + 14, outline="white", width=3)
        if scroll and self.photo:
            W, H = self.photo.width(), self.photo.height()
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            vx0, vx1 = self.canvas.xview()
            vy0, vy1 = self.canvas.yview()
            if not (vx0 * W < x < vx1 * W and vy0 * H < y < vy1 * H):
                self.canvas.xview_moveto(max(0, (x - cw / 2) / W))
                self.canvas.yview_moveto(max(0, (y - ch / 2) / H))


# ---------------------------------------------------------------------------------------
class CodeTab(ttk.Frame):
    """Assembly listing and/or its literal C translation (lift.py)."""
    ADDR = re.compile(r"\b([89AB][0-9A-F]{5})\b")

    def __init__(self, parent, app: App):
        super().__init__(parent, padding=8)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="SNES address $").pack(side="left")
        self.addr = tk.StringVar(value="81B516")
        e = ttk.Entry(top, textvariable=self.addr, width=10)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self.go())
        ttk.Button(top, text="Show", command=self.go).pack(side="left", padx=6)
        ttk.Label(top, text="View:").pack(side="left", padx=(12, 4))
        self.view = tk.StringVar(value="asm")
        for val, label in (("asm", "Assembly"), ("c", "C"), ("literal", "Literal C"), ("both", "Side by side")):
            ttk.Radiobutton(top, text=label, value=val, variable=self.view,
                            command=self.layout).pack(side="left", padx=2)
        about = ttk.Label(self, text="C: decompiled — one function per state/step, registers folded into expressions, "
                                     "if/else rebuilt, names from what we've decoded. Literal C: one statement per "
                                     "instruction. Neither is compiled; names marked (?) in defs/lift are guesses. "
                                     "Side by side (Assembly + C): click a line to find the matching code in the other "
                                     "pane.", foreground="#666", wraplength=px(1100), justify="left")
        about.pack(fill="x", pady=(4, 0))
        about.bind("<Configure>", lambda e: about.configure(wraplength=max(200, e.width - 8)))
        self.panes = ttk.PanedWindow(self, orient="horizontal")
        self.panes.pack(fill="both", expand=True, pady=6)
        self.asm_frame, self.asm = self._text_pane("Assembly")
        self.c_frame, self.c = self._text_pane("C")
        self.layout()

    def _text_pane(self, title):
        f = ttk.Frame(self.panes)
        ttk.Label(f, text=title, font="Bold").grid(row=0, column=0, sticky="w")
        t = tk.Text(f, font="Mono", wrap="none", undo=False)
        vs = ttk.Scrollbar(f, orient="vertical", command=t.yview)
        hs = ttk.Scrollbar(f, orient="horizontal", command=t.xview)
        t.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        t.grid(row=1, column=0, sticky="nsew")
        vs.grid(row=1, column=1, sticky="ns")
        hs.grid(row=2, column=0, sticky="ew")
        f.rowconfigure(1, weight=1)
        f.columnconfigure(0, weight=1)
        t.tag_configure("label", foreground="#0a58ca", font="MonoBold")
        t.tag_configure("note", foreground="#2e7d32")
        t.tag_configure("hit", background="#fff3b0")
        t.bind("<ButtonRelease-1>", lambda e, t=t: self.sync_from(t))
        return f, t

    def layout(self):
        for f in (self.asm_frame, self.c_frame):
            try:
                self.panes.forget(f)
            except tk.TclError:
                pass
        v = self.view.get()
        if v in ("asm", "both"):
            self.panes.add(self.asm_frame, weight=1)
        if v in ("c", "literal", "both"):
            self.panes.add(self.c_frame, weight=1)
        if self.c.get("1.0", "2.0").strip() and getattr(self, "_shown", None) != v:
            self.go()

    def refresh(self):
        pass

    def show(self, addr):
        self.addr.set(f"{addr:06X}")
        self.app.nb.select(self)
        self.go()

    def go(self):
        try:
            a = int(self.addr.get().lstrip("$"), 16)
            asm = listing(self.app.g.rom, a)
            if self.view.get() == "literal":
                c, self.cmap = lift(self.app.g.rom, a), {}
            else:
                boss = next((b for b in BOSSES.values() if b.routine == a), None)
                c, self.cmap = decompile_with_map(self.app.g.rom, a, boss)
        except Exception as e:
            messagebox.showerror("Can't disassemble", str(e))
            return
        self._shown = self.view.get()
        self._fill(self.asm, asm, ";")
        self._fill(self.c, c, "//")

    def _fill(self, t, text, comment):
        t.configure(state="normal")
        t.delete("1.0", "end")
        for line in text.splitlines():
            if line and not line.startswith(" ") and line.endswith(":"):
                t.insert("end", line + "\n", "label")
            elif comment in line:
                code, note = line.split(comment, 1)
                t.insert("end", code)
                t.insert("end", comment + note + "\n", "note")
            else:
                t.insert("end", line + "\n")
        t.configure(state="disabled")

    def sync_from(self, src):
        if self.view.get() != "both":
            return
        dst = self.c if src is self.asm else self.asm
        for t in (self.asm, self.c):
            t.tag_remove("hit", "1.0", "end")
        src.tag_add("hit", "insert linestart", "insert lineend")
        if src is self.c and self.cmap:
            n = int(src.index("insert").split(".")[0])
            addr = self.cmap.get(n) or max((v for k, v in self.cmap.items() if k <= n), default=None)
            if addr is None:
                return
            pos = self.asm.search(f"{addr:06X}", "1.0", nocase=True)
            if pos:
                self.asm.tag_add("hit", f"{pos} linestart", f"{pos} lineend")
                self.asm.see(pos)
            return
        m = self.ADDR.search(src.get("insert linestart", "insert lineend").upper())
        if not m:
            return
        target = int(m.group(1), 16)
        if dst is self.c and self.cmap:
            # the C line produced from this instruction, or the closest earlier one
            best = max((k for k, v in self.cmap.items() if v <= target and v >> 16 == target >> 16
                        and target - v < 0x40), key=lambda k: self.cmap[k], default=None)
            if best:
                self.c.tag_add("hit", f"{best}.0", f"{best}.end")
                self.c.see(f"{best}.0")
            return
        pos = dst.search(m.group(1), "1.0", nocase=True)
        if pos:
            dst.tag_add("hit", f"{pos} linestart", f"{pos} lineend")
            dst.see(pos)


def main():
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PROJECT
    App(project).mainloop()


if __name__ == "__main__":
    main()
