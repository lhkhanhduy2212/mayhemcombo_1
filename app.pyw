"""Mayhem Combo - overlay goi y augment ARAM Mayhem (Windows).

Chay: nhap dup "Chay_MayhemCombo.bat" (hoac: pyw app.pyw).
Phim tat: F8 an/hien, F9 quet bang augment (doi trong config.json).
"""
from __future__ import annotations

import json
import os
import queue
import ssl
import sys
import threading
import time
import traceback
import urllib.request
import tkinter as tk
import tkinter.font as tkfont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E  # noqa: E402
import ocr as OCR  # noqa: E402

IS_WIN = sys.platform.startswith("win")
CONFIG_PATH = os.path.join(E.user_dir(), "config.json")
LOG_PATH = os.path.join(E.user_dir(), "log.txt")
LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"

T = dict(bg="#121418", panel="#1a1d23", panel2="#252a33", fg="#ecebe7", dim="#8f97a2", accent="#4fc3f7",
         good="#7bd88f", bad="#ff7b72", warn="#f0c674", border="#323844", sel="#2f5f7a", gold="#ffd23f")
RARITY_COLOR = {"kSilver": "#c9d2dc", "kGold": "#f2c14e", "kPrismatic": "#d6a2ff"}
GRADE_COLOR = {"Rất mạnh": "#7bd88f", "Tốt": "#b5e07a", "Ổn": "#f0c674", "Yếu": "#ff9e64", "Tránh": "#ff7b72"}
KIND_COLOR = {"+": T["good"], "-": T["bad"], "i": T["dim"], "!": T["warn"]}
KIND_ICON = {"+": "▲", "-": "▼", "i": "•", "!": "!"}
SLOT_VN = ["trái", "giữa", "phải"]

_log_lock = threading.Lock()


def log(msg: str):
    with _log_lock:
        try:
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 512 * 1024:
                os.replace(LOG_PATH, LOG_PATH + ".old")
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
        except Exception:  # noqa: BLE001
            pass


def load_config() -> dict:
    cfg = {"hotkey": "F8", "alpha": 0.95, "pos": None, "width": 300, "poll_seconds": 1.5,
           "auto_new_game": True, "ocr": True, "ocr_hotkey": "F9", "ocr_lang": "en-US",
           "aug_lang": "vi", "badges": True, "badge_offset": 0.21, "badge_seconds_manual": 40,
           "badge_selftest": True}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:  # noqa: BLE001
        pass
    return cfg


def save_config(cfg: dict):
    try:
        cfg.pop("geometry", None)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        log(f"save config: {e}")


# --------------------------------------------------------------------------- threads

class LivePoller(threading.Thread):
    """Doc Live Client Data API cua game (chi doc, API chinh thuc cua Riot, chay tren may ban)."""

    def __init__(self, q: queue.Queue, interval: float):
        super().__init__(daemon=True)
        self.q = q
        self.interval = max(0.5, float(interval))
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # chung chi tu ky cua Riot tren 127.0.0.1
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPSHandler(context=ctx))
        self.dumped = False

    def run(self):
        last_ok = None
        while True:
            try:
                with self.opener.open(LIVE_URL, timeout=1.2) as r:
                    js = json.loads(r.read().decode("utf-8"))
                state = E.parse_live(js)
                if not self.dumped and state.get("alias"):
                    self.dumped = True
                    try:
                        with open(os.path.join(E.user_dir(), "live_sample.json"), "w", encoding="utf-8") as f:
                            json.dump(js, f, ensure_ascii=False, indent=1)
                    except Exception:  # noqa: BLE001
                        pass
                self.q.put(("live", state))
                last_ok = True
            except Exception:  # noqa: BLE001
                if last_ok is not False:
                    self.q.put(("live", None))
                last_ok = False
            time.sleep(self.interval if last_ok else 4.0)


VK = {f"F{i}": 0x6F + i for i in range(1, 13)}
VK.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})
VK.update({str(d): 0x30 + d for d in range(10)})
VK.update({"INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22, "`": 0xC0})


def parse_combo(combo: str):
    mods, vk = 0x4000, None  # MOD_NOREPEAT
    for part in (combo or "").upper().replace(" ", "").split("+"):
        if part in ("CTRL", "CONTROL"):
            mods |= 0x2
        elif part == "SHIFT":
            mods |= 0x4
        elif part == "ALT":
            mods |= 0x1
        elif part:
            vk = VK.get(part)
    return mods, vk


class HotkeyThread(threading.Thread):
    """Phim tat toan cuc (Windows RegisterHotKey), dung duoc ca khi dang o trong game."""

    def __init__(self, q: queue.Queue, combos: list):
        super().__init__(daemon=True)
        self.q = q
        self.combos = [(i, c) for i, c in combos if c]

    def run(self):
        if not IS_WIN or not self.combos:
            return
        try:
            import ctypes
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            for hid, combo in self.combos:
                mods, vk = parse_combo(combo)
                if vk is None or not user32.RegisterHotKey(None, hid, mods, vk):
                    self.q.put(("hotkey_fail", combo))
            msg = wt.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):
                    break
                if msg.message == 0x0312:  # WM_HOTKEY
                    self.q.put(("hotkey", int(msg.wParam)))
        except Exception as e:  # noqa: BLE001
            log(f"hotkey: {e}")


def bg_task(q: queue.Queue, tag: str, fn, *args):
    def run():
        try:
            q.put((tag, fn(*args)))
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
            q.put((tag, None))
    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------- widgets

class AutoEntry(tk.Entry):
    """O nhap co goi y (tim khong dau). Danh sach goi y nam trong cua so chinh."""

    def __init__(self, master, app, suggest, on_pick, placeholder="", on_escape=None, **kw):
        super().__init__(master, bg=T["panel2"], fg=T["fg"], insertbackground=T["fg"], relief="flat",
                         highlightthickness=1, highlightbackground=T["border"], highlightcolor=T["accent"],
                         font=app.f_small, **kw)
        self.app = app
        self.suggest = suggest
        self.on_pick = on_pick
        self.on_escape = on_escape
        self.placeholder = placeholder
        self.items: list = []
        self.lb = None
        self._ph_on = False
        self._show_placeholder()
        self.bind("<KeyRelease>", self._on_key)
        self.bind("<Down>", lambda e: self._move(1))
        self.bind("<Up>", lambda e: self._move(-1))
        self.bind("<Return>", self._on_enter)
        self.bind("<KP_Enter>", self._on_enter)
        self.bind("<Escape>", self._on_esc)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", lambda e: self.after(200, self._maybe_close))

    def _show_placeholder(self):
        if not self.get() and self.placeholder:
            self._ph_on = True
            self.config(fg=T["dim"])
            self.insert(0, self.placeholder)

    def _on_focus_in(self, _e=None):
        if self._ph_on:
            self.delete(0, "end")
            self.config(fg=T["fg"])
            self._ph_on = False

    def clear(self):
        self.close()
        self.delete(0, "end")
        self._ph_on = False
        self._show_placeholder()

    def text(self) -> str:
        return "" if self._ph_on else self.get()

    def _on_key(self, e):
        if e.keysym in ("Up", "Down", "Return", "KP_Enter", "Escape", "Shift_L", "Shift_R",
                        "Control_L", "Control_R", "Alt_L", "Alt_R"):
            return
        q = self.text().strip()
        self.items = self.suggest(q) if q else []
        self._render()

    def _render(self):
        if not self.items:
            self.close()
            return
        root = self.app.root
        if self.lb is None:
            self.lb = tk.Listbox(root, bg=T["panel2"], fg=T["fg"], selectbackground=T["sel"],
                                 selectforeground=T["fg"], relief="flat", highlightthickness=1,
                                 highlightbackground=T["accent"], activestyle="none", font=self.app.f_small,
                                 exportselection=False, takefocus=0)
            self.lb.bind("<ButtonRelease-1>", self._on_click)
        self.lb.delete(0, "end")
        for i, (_id, label, color) in enumerate(self.items):
            self.lb.insert("end", " " + label)
            if color:
                self.lb.itemconfig(i, fg=color)
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(0)
        self.lb.config(height=min(6, len(self.items)))
        self.update_idletasks()
        x = self.winfo_rootx() - root.winfo_rootx()
        y = self.winfo_rooty() - root.winfo_rooty() + self.winfo_height()
        need = y + self.lb.winfo_reqheight() + 4
        if need > root.winfo_height():  # cua so co gian theo noi dung -> noi rong tam de hien goi y
            root.geometry(f"{root.winfo_width()}x{need}")
        self.lb.place(x=x, y=y, width=self.winfo_width())
        self.lb.lift()

    def _move(self, d):
        if not self.items or not self.lb:
            return "break"
        cur = self.lb.curselection()
        i = max(0, min(len(self.items) - 1, (cur[0] if cur else -1) + d))
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(i)
        self.lb.see(i)
        return "break"

    def _pick_index(self, i):
        if 0 <= i < len(self.items):
            _id = self.items[i][0]
            self.close()
            self.delete(0, "end")
            self.on_pick(_id)

    def _on_enter(self, _e=None):
        if self.items and self.lb:
            cur = self.lb.curselection()
            self._pick_index(cur[0] if cur else 0)
        return "break"

    def _on_esc(self, _e=None):
        self.close()
        if self.on_escape:
            self.on_escape()
        return "break"

    def _on_click(self, _e=None):
        if self.lb:
            cur = self.lb.curselection()
            if cur:
                self._pick_index(cur[0])

    def _maybe_close(self):
        try:
            f = self.focus_get()
        except Exception:  # noqa: BLE001
            f = None
        if f is not self:
            self.close()

    def close(self):
        if self.lb is not None:
            try:
                self.lb.destroy()
            except tk.TclError:
                pass
            self.lb = None
            self.app.fit_soon()
        self.items = []


def small_button(master, text, cmd, app, fg=None, bg=None, padx=6):
    return tk.Button(master, text=text, command=cmd, bg=bg or T["panel2"], fg=fg or T["fg"],
                     activebackground=T["sel"], activeforeground=T["fg"], relief="flat", bd=0,
                     highlightthickness=0, font=app.f_small, padx=padx, pady=1, cursor="hand2")


def link(master, text, cmd, app, fg=None, bg=None, font=None):
    lb = tk.Label(master, text=text, fg=fg or T["dim"], bg=bg or T["bg"], font=font or app.f_small, cursor="hand2")
    lb.bind("<Button-1>", lambda e: cmd())
    return lb


# --------------------------------------------------------------------------- PICK ME badges

BADGE_KEY = "#010203"  # mau "trong suot" cua cua so nhan


class BadgeLayer:
    """3 nhan noi tren 3 the augment trong game: "★ PICK ME" o the nen chon, diem o the con lai.

    Cua so trong suot, click xuyen qua, khong gianh focus. KHONG an bang cach day ra ngoai man hinh
    (Tk co the bo qua vi tri moi -> nhan ket ngoai man hinh): tren Windows an/hien bang Win32
    (SW_HIDE / SetWindowPos), sau do kiem tra lai vi tri that va dat lai neu lech."""

    def __init__(self, app, n=3):
        self.app = app
        self.wins = []
        self.rects: list = [None] * n
        self.hwnds: list = [None] * n
        self.shown = False
        self.ready = False
        for _ in range(n):
            w = tk.Toplevel(app.root)
            w.overrideredirect(True)
            w.configure(bg=BADGE_KEY)
            try:
                w.attributes("-topmost", True)
                if IS_WIN:
                    w.attributes("-transparentcolor", BADGE_KEY)
            except tk.TclError:
                pass
            lbl = tk.Label(w, text="", bg=BADGE_KEY, bd=0, highlightthickness=0)
            lbl.pack()
            w.geometry("4x4+0+0")
            if not IS_WIN:
                w.withdraw()
            self.wins.append((w, lbl))
        app.root.after(250, self._setup)

    def _setup(self):
        for i, (w, _) in enumerate(self.wins):
            try:
                w.update_idletasks()
                OCR.make_badge_window(w)
                self.hwnds[i] = OCR.root_hwnd(w)
                if IS_WIN:
                    OCR.hide_window(self.hwnds[i])
            except tk.TclError:
                pass
        self.ready = True

    def show(self, items):
        """items: [(x_giua, y_day, text, fg, bg, font_px), ...] toa do man hinh (pixel that)."""
        if not self.ready:
            self.app.root.after(200, lambda: self.show(items))
            return
        for idx, (w, lbl) in enumerate(self.wins):
            it = items[idx] if idx < len(items) else None
            if it is None:
                self._hide_one(idx)
                continue
            x, y, text, fg, bg, px = it
            lbl.config(text=text, fg=fg, bg=bg, font=self.app.badge_font(px), padx=max(6, px // 2),
                       pady=max(2, px // 8))
            w.update_idletasks()
            bw, bh = lbl.winfo_reqwidth(), lbl.winfo_reqheight()
            rect = (int(x - bw / 2), int(y - bh), bw, bh)
            self.rects[idx] = rect
            self._place(idx)
        self.shown = any(r is not None for r in self.rects)
        if self.shown:
            self.app.root.after(80, self.verify)

    def _place(self, idx):
        w, _ = self.wins[idx]
        x, y, bw, bh = self.rects[idx]
        w.geometry(f"{bw}x{bh}+{x}+{y}")
        if IS_WIN:
            if not OCR.force_topmost(self.hwnds[idx], self.rects[idx]):
                w.lift()
        else:
            if w.state() == "withdrawn":
                w.deiconify()
            w.lift()

    def verify(self):
        """Vi tri that co dung khong? Lech thi dat lai (va dua len tren cung)."""
        for idx, rect in enumerate(self.rects):
            if not rect:
                continue
            w, _ = self.wins[idx]
            real = OCR.get_rect(self.hwnds[idx]) if IS_WIN else (w.winfo_rootx(), w.winfo_rooty(),
                                                                 w.winfo_width(), w.winfo_height())
            if not real or abs(real[0] - rect[0]) > 2 or abs(real[1] - rect[1]) > 2:
                self._place(idx)
            elif IS_WIN:
                OCR.force_topmost(self.hwnds[idx], rect)

    def raise_all(self):
        if self.shown:
            self.verify()

    def _hide_one(self, idx):
        w, lbl = self.wins[idx]
        self.rects[idx] = None
        if IS_WIN:
            OCR.hide_window(self.hwnds[idx])
        else:
            w.withdraw()
        lbl.config(text="", bg=BADGE_KEY)

    def hide(self):
        if not self.shown:
            return
        for idx in range(len(self.wins)):
            if self.rects[idx] is not None:
                self._hide_one(idx)
        self.shown = False

    def report(self) -> str:
        d = {f"badge{i}": h for i, h in enumerate(self.hwnds) if self.rects[i]}
        d["overlay"] = OCR.root_hwnd(self.app.root)
        want = " ".join(f"badge{i}@{r}" for i, r in enumerate(self.rects) if r)
        return f"muon: {want} | thuc te: " + OCR.window_report(d)


# --------------------------------------------------------------------------- app

class App:
    def __init__(self):
        self.cfg = load_config()
        self.q: queue.Queue = queue.Queue()
        self.eng = E.Engine(log=log)
        self.eng.prefer_en = str(self.cfg.get("aug_lang", "vi")).lower().startswith("en")
        self.cid = None
        self.owned: list = []
        self.offers: list = [None, None, None]
        self.live = None
        self.last_game_time = None
        self.collapsed = False
        self.loading_champ: set = set()
        self.expanded: set = set()
        self.tips_open = False
        self._flash_msg = None
        self._fit_job = None
        # OCR
        self.watcher = None
        self.capture_excluded = False
        self._ocr_last_key = None
        self._ocr_agree = 0
        self._ocr_miss = 0
        self._ocr_published = None
        self._ocr_taken_key = None
        self._ocr_errors_shown: set = set()
        self._offer_from_ocr = False
        # PICK ME
        self.badges = None
        self._badge_fonts: dict = {}
        self._offer_geo = None
        self._offer_pos = [None, None, None]
        self._badge_until = 0.0
        self._badge_logged_key = None
        self._last_ranked: list = []
        self._scan_started = 0.0
        self._last_match = 0.0
        self._selftest_until = 0.0

        if IS_WIN:
            try:
                import ctypes
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # toa do vat ly cho OCR + nhan
                except Exception:  # noqa: BLE001
                    ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:  # noqa: BLE001
                pass
        self.root = tk.Tk()
        self.root.title("Mayhem Combo")
        self.root.configure(bg=T["border"])
        self.root.overrideredirect(True)  # khong vien, khong thanh tieu de -> gon nhat
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        fams = set(tkfont.families())
        fam = next((f for f in ("Segoe UI", "Segoe UI Variable Text", "Arial", "DejaVu Sans") if f in fams),
                   "TkDefaultFont")
        self.font_family = fam
        self.f_norm = tkfont.Font(family=fam, size=10)
        self.f_small = tkfont.Font(family=fam, size=9)
        self.f_bold = tkfont.Font(family=fam, size=10, weight="bold")
        self.f_tiny = tkfont.Font(family=fam, size=8)
        try:
            self.root.attributes("-topmost", True)
            self.root.attributes("-alpha", float(self.cfg.get("alpha", 0.95)))
        except tk.TclError:
            pass
        self.W = self.px(int(self.cfg.get("width", 300)))
        pos = self.cfg.get("pos")
        if isinstance(pos, list) and len(pos) == 2:
            self.x, self.y = int(pos[0]), int(pos[1])
        else:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            self.x, self.y = max(0, sw - self.W - self.px(8)), self.px(40)
        self.root.geometry(f"{self.W}x60+{self.x}+{self.y}")

        self._build()
        self.recalc()
        LivePoller(self.q, self.cfg.get("poll_seconds", 1.5)).start()
        HotkeyThread(self.q, [(1, self.cfg.get("hotkey", "F8")), (2, self.cfg.get("ocr_hotkey", "F9"))]).start()
        bg_task(self.q, "engine", E.fetch_updates, self.eng.ddv, log)
        if self.cfg.get("ocr", True) and IS_WIN:
            self.watcher = OCR.OcrWatcher(self.q, self.cfg.get("ocr_lang", "en-US"), log)
            self.watcher.start()
        if self.cfg.get("badges", True):
            self.badges = BadgeLayer(self)
            if self.cfg.get("badge_selftest", True):
                self.root.after(1500, self._badge_selftest)
        self.root.after(100, self._pump)
        self.root.after(800, self._exclude_capture)
        self.root.after(1000, self._tick)

    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    def _exclude_capture(self):
        self.capture_excluded = OCR.exclude_from_capture(self.root)

    # ------------------------------------------------------------- layout
    def _build(self):
        r = self.root
        self.outer = tk.Frame(r, bg=T["bg"])
        self.outer.pack(fill="both", expand=True, padx=1, pady=1)
        hd = tk.Frame(self.outer, bg=T["panel"], padx=self.px(8), pady=self.px(5))
        hd.pack(fill="x")
        self.header = hd
        self.lbl_dot = tk.Label(hd, text="●", fg=T["dim"], bg=T["panel"], font=self.f_small)
        self.lbl_dot.pack(side="left")
        self.lbl_champ = tk.Label(hd, text="Chọn tướng ▾", fg=T["fg"], bg=T["panel"], font=self.f_bold,
                                  cursor="hand2", anchor="w")
        self.lbl_champ.pack(side="left", padx=(self.px(5), 0))
        small_button(hd, "✕", self.on_close, self, fg=T["dim"], bg=T["panel"], padx=4).pack(side="right")
        self.btn_min = small_button(hd, "—", self.toggle_collapse, self, fg=T["dim"], bg=T["panel"], padx=4)
        self.btn_min.pack(side="right")
        self.btn_scan = small_button(hd, "⟳ Quét", self.manual_scan, self, fg=T["bg"], bg=T["accent"], padx=8)
        self.btn_scan.pack(side="right", padx=(0, self.px(4)))
        # keo de di chuyen cua so (khong co thanh tieu de)
        for wdg in (hd, self.lbl_dot, self.lbl_champ):
            wdg.bind("<ButtonPress-1>", self._drag_start)
            wdg.bind("<B1-Motion>", self._drag_move)
            wdg.bind("<ButtonRelease-1>", self._drag_end)

        self.lbl_flash = tk.Label(self.outer, text="", fg=T["warn"], bg=T["panel2"], font=self.f_tiny,
                                  anchor="w", justify="left", padx=self.px(8), pady=self.px(3))
        self.champ_row = tk.Frame(self.outer, bg=T["bg"], padx=self.px(8), pady=self.px(4))
        self.ent_champ = AutoEntry(self.champ_row, self, self._suggest_champ, self._pick_champ,
                                   placeholder="gõ tên tướng…", on_escape=self._hide_champ_row)
        self.ent_champ.pack(fill="x", ipady=self.px(2))

        self.body = tk.Frame(self.outer, bg=T["bg"], padx=self.px(8), pady=self.px(6))
        self.body.pack(fill="both", expand=True)
        self.offers_frame = tk.Frame(self.body, bg=T["bg"])
        self.offers_frame.pack(fill="x")
        self.owned_frame = tk.Frame(self.body, bg=T["bg"])
        self.owned_frame.pack(fill="x", pady=(self.px(6), 0))
        self.add_row = tk.Frame(self.body, bg=T["bg"])
        self.ent_add = AutoEntry(self.add_row, self, self._suggest_owned, self._pick_owned,
                                 placeholder="thêm augment đã có…", on_escape=self._hide_add_row)
        self.ent_add.pack(fill="x", ipady=self.px(1))
        self.lbl_tips = link(self.body, "▸ Gợi ý build", self.toggle_tips, self)
        self.lbl_tips.pack(fill="x", anchor="w", pady=(self.px(6), 0))
        self.tips_frame = tk.Frame(self.body, bg=T["bg"])

    def _drag_start(self, e):
        self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def _drag_move(self, e):
        if not getattr(self, "_drag", None):
            return
        sx, sy, wx, wy, moved = self._drag
        dx, dy = e.x_root - sx, e.y_root - sy
        if moved or abs(dx) + abs(dy) > 4:
            self._drag = (sx, sy, wx, wy, True)
            self.x, self.y = wx + dx, wy + dy
            self.root.geometry(f"+{self.x}+{self.y}")

    def _drag_end(self, e):
        d = getattr(self, "_drag", None)
        self._drag = None
        if d and not d[4] and e.widget is self.lbl_champ:
            self._toggle_champ_row()
        elif d and d[4]:
            self.cfg["pos"] = [self.x, self.y]

    def fit_soon(self):
        if self._fit_job is None:
            self._fit_job = self.root.after(30, self.fit)

    def fit(self):
        """Cua so tu co gian chieu cao theo noi dung."""
        self._fit_job = None
        try:
            self.root.update_idletasks()
            h = self.outer.winfo_reqheight() + 2
            self.root.geometry(f"{self.W}x{h}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        except tk.TclError:
            pass

    # ------------------------------------------------------------- small UI pieces
    def _toggle_champ_row(self):
        if self.champ_row.winfo_ismapped():
            self._hide_champ_row()
        else:
            self.champ_row.pack(fill="x", after=self.header)
            self.ent_champ.clear()
            self._focus(self.ent_champ)
            self.fit_soon()

    def _hide_champ_row(self):
        self.champ_row.pack_forget()
        self.fit_soon()

    def _show_add_row(self):
        self.add_row.pack(fill="x", pady=(self.px(4), 0), after=self.owned_frame)
        self.ent_add.clear()
        self._focus(self.ent_add)
        self.fit_soon()

    def _hide_add_row(self):
        self.add_row.pack_forget()
        self.fit_soon()

    def _focus(self, ent):
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        ent.focus_set()

    def toggle_tips(self):
        self.tips_open = not self.tips_open
        self.recalc()

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.body.pack_forget()
            self.champ_row.pack_forget()
            self.lbl_flash.pack_forget()
            self.btn_min.config(text="+")
        else:
            self.body.pack(fill="both", expand=True)
            self.btn_min.config(text="—")
            self._paint_flash()
        self.fit_soon()

    def toggle_visible(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            OCR.force_topmost(OCR.root_hwnd(self.root))
        else:
            self.root.withdraw()

    def flash(self, msg: str, ms=6000):
        self._flash_msg = msg
        self._paint_flash()
        self.root.after(ms, self._clear_flash, msg)

    def _clear_flash(self, msg):
        if self._flash_msg == msg:
            self._flash_msg = None
            self._paint_flash()

    def _paint_flash(self):
        if self._flash_msg and not self.collapsed:
            self.lbl_flash.config(text=self._flash_msg, wraplength=self.W - self.px(20))
            self.lbl_flash.pack(fill="x", after=self.header)
        else:
            self.lbl_flash.pack_forget()
        self.fit_soon()

    # ------------------------------------------------------------- suggestions
    def _aug_label(self, aid: int) -> str:
        a = self.eng.augs.get(aid, {})
        vn = self.eng.vn_aug.get(aid)
        en = self.eng.en_aug.get(aid) or a.get("en", "")
        r = E.RARITY_VN.get(a.get("rarity"), "")
        if vn and E.norm(vn) != E.norm(en):
            return f"{vn} · {en} · {r}"
        return f"{en or vn} · {r}"

    def _suggest_owned(self, q):
        ids = self.eng.search_augs(q, cid=self.cid, exclude=set(self.owned), limit=6)
        return [(a, self._aug_label(a), RARITY_COLOR.get(self.eng.augs[a].get("rarity"))) for a in ids]

    def _suggest_slot(self, q):
        rar = next((self.eng.augs[a].get("rarity") for a in self.offers if a), None)
        ids = self.eng.search_augs(q, rarity=rar, cid=self.cid, exclude=set(self.owned) | set(self.offers), limit=6)
        return [(a, self._aug_label(a), RARITY_COLOR.get(self.eng.augs[a].get("rarity"))) for a in ids]

    def _suggest_champ(self, q):
        out = []
        for c in self.eng.search_champs(q, limit=6):
            en = self.eng.champs[c].get("en", "")
            vn = self.eng.champ_name(c)
            out.append((c, vn if E.norm(vn) == E.norm(en) else f"{vn} · {en}", None))
        return out

    # ------------------------------------------------------------- actions
    def _pick_champ(self, cid):
        self._hide_champ_row()
        self.set_champ(cid)

    def set_champ(self, cid):
        if cid == self.cid:
            return
        self.cid = cid
        self._load_champ(cid)
        self.recalc()

    def _load_champ(self, cid):
        if cid is None or cid in self.loading_champ or cid in self.eng._fresh_champs:
            return
        self.loading_champ.add(cid)
        dv = self.eng.detail_version
        bg_task(self.q, "champ_data", lambda c=cid: (c, dv, E.fetch_champ(c, dv, log)))

    def _pick_owned(self, aid):
        if aid not in self.owned:
            self.owned.append(aid)
        self._hide_add_row()
        self.recalc()

    def remove_owned(self, aid):
        if aid in self.owned:
            self.owned.remove(aid)
        self.recalc()

    def _fill_slot(self, i, aid):
        self.offers[i] = aid
        self.recalc()

    def take(self, aid):
        if aid not in self.owned:
            self.owned.append(aid)
        self._ocr_taken_key = self._ocr_published
        self.clear_offers()

    def clear_offers(self):
        self.offers = [None, None, None]
        self._offer_pos = [None, None, None]
        self._badge_until = 0.0
        self.expanded.clear()
        if self.badges:
            self.badges.hide()
        self.recalc()

    def new_game(self, auto=False):
        self.owned = []
        self._ocr_published = self._ocr_taken_key = self._ocr_last_key = None
        self.clear_offers()
        if auto:
            self.flash("Ván mới — đã xoá augment của ván trước.")

    def toggle_expand(self, aid):
        if aid in self.expanded:
            self.expanded.discard(aid)
        else:
            self.expanded.add(aid)
        self.recalc()

    # ------------------------------------------------------------- render
    def recalc(self):
        eng = self.eng
        wl = self.W - self.px(24)
        # header
        if self.live and self.live.get("alias"):
            self.lbl_dot.config(fg=T["good"])
            name = f"{eng.champ_name(self.cid)} · {self.live.get('level')}"
        else:
            self.lbl_dot.config(fg=T["dim"])
            name = eng.champ_name(self.cid) if self.cid is not None else "Chọn tướng"
        self.lbl_champ.config(text=name + " ▾")

        # offers
        for w in self.offers_frame.winfo_children():
            w.destroy()
        offers = [a for a in self.offers if a is not None]
        ranked: list = []
        if not offers:
            tk.Label(self.offers_frame, text="Khi bảng augment hiện ra, app tự quét lúc bạn chết. "
                                             "Hoặc bấm ⟳ Quét / F9.",
                     fg=T["dim"], bg=T["bg"], font=self.f_tiny, wraplength=wl, justify="left",
                     anchor="w").pack(fill="x")
        else:
            ranked = eng.rank_offers(self.cid, offers, self.owned, self.live)
            for i, s in enumerate(ranked):
                self._row(i, s, best=(i == 0 and len(ranked) > 1), wl=wl)
            for i, a in enumerate(self.offers):
                if a is None:
                    self._missing_row(i)
        self._last_ranked = ranked
        self._refresh_badges()

        # owned
        for w in self.owned_frame.winfo_children():
            w.destroy()
        self._owned_chips(wl)

        # tips
        self.lbl_tips.config(text=("▾ Gợi ý build" if self.tips_open else "▸ Gợi ý build"))
        for w in self.tips_frame.winfo_children():
            w.destroy()
        if self.tips_open:
            self.tips_frame.pack(fill="x", after=self.lbl_tips)
            self._tips(wl)
        else:
            self.tips_frame.pack_forget()
        self.fit_soon()

    def _row(self, i, s: E.Scored, best: bool, wl: int):
        eng = self.eng
        a = eng.augs.get(s.aid, {})
        gc = GRADE_COLOR.get(s.grade, T["accent"])
        row = tk.Frame(self.offers_frame, bg=T["panel"])
        row.pack(fill="x", pady=(0, self.px(3)))
        tk.Frame(row, bg=T["gold"] if best else gc, width=self.px(3)).pack(side="left", fill="y")
        inner = tk.Frame(row, bg=T["panel"], padx=self.px(6), pady=self.px(3))
        inner.pack(side="left", fill="both", expand=True)
        top = tk.Frame(inner, bg=T["panel"])
        top.pack(fill="x")
        mark = tk.Label(top, text="★" if best else str(i + 1), fg=T["gold"] if best else T["dim"], bg=T["panel"],
                        font=self.f_bold, width=2, anchor="w")
        mark.pack(side="left")
        btn = small_button(top, "Lấy", lambda aid=s.aid: self.take(aid), self,
                           fg=T["bg"] if best else T["fg"], bg=T["gold"] if best else T["panel2"])
        btn.pack(side="right")
        tk.Label(top, text=f"{s.total:+.1f}", fg=gc, bg=T["panel"], font=self.f_bold).pack(
            side="right", padx=(0, self.px(6)))
        nm = tk.Label(top, text=eng.aug_name(s.aid), fg=RARITY_COLOR.get(a.get("rarity"), T["fg"]), bg=T["panel"],
                      font=self.f_bold, anchor="w", justify="left", wraplength=wl - self.px(110))
        nm.pack(side="left", fill="x", expand=True)
        slot = self.offers.index(s.aid) if s.aid in self.offers else None
        shorts = [r.short for r in s.reasons if r.short][:2]
        sub = " · ".join(([f"thẻ {SLOT_VN[slot]}"] if slot is not None else []) + [s.grade] + shorts)
        sl = tk.Label(inner, text=sub, fg=T["dim"], bg=T["panel"], font=self.f_tiny, anchor="w", justify="left",
                      wraplength=wl - self.px(14))
        sl.pack(fill="x", padx=(self.px(18), 0))
        if s.aid in self.expanded:
            for r in s.reasons[:6]:
                tk.Label(inner, text=f"{KIND_ICON.get(r.kind, '•')} {r.text}", fg=KIND_COLOR.get(r.kind, T["dim"]),
                         bg=T["panel"], font=self.f_tiny, wraplength=wl - self.px(20), justify="left",
                         anchor="w").pack(fill="x", padx=(self.px(18), 0))
        for wdg in (row, inner, top, nm, sl, mark):
            wdg.bind("<Button-1>", lambda e, aid=s.aid: self.toggle_expand(aid))
            wdg.config(cursor="hand2")

    def _missing_row(self, i):
        row = tk.Frame(self.offers_frame, bg=T["panel"], padx=self.px(6), pady=self.px(3))
        row.pack(fill="x", pady=(0, self.px(3)))
        tk.Label(row, text="?", fg=T["warn"], bg=T["panel"], font=self.f_bold, width=2, anchor="w").pack(side="left")
        ent = AutoEntry(row, self, self._suggest_slot, lambda aid, i=i: self._fill_slot(i, aid),
                        placeholder=f"thẻ {SLOT_VN[i]} chưa đọc được — gõ tên…")
        ent.pack(side="left", fill="x", expand=True)

    def _owned_chips(self, wl):
        eng = self.eng
        rowf = tk.Frame(self.owned_frame, bg=T["bg"])
        rowf.pack(fill="x")
        tk.Label(rowf, text=f"Đã có {len(self.owned)}/4", fg=T["dim"], bg=T["bg"], font=self.f_tiny).pack(side="left")
        if self.owned:
            link(rowf, "xoá hết", self.new_game, self, fg=T["dim"], font=self.f_tiny).pack(side="right")
        used = self.px(70)
        line = rowf
        for aid in self.owned:
            name = eng.aug_name(aid)
            wpx = self.f_tiny.measure(name) + self.px(26)
            if used + wpx > wl:
                line = tk.Frame(self.owned_frame, bg=T["bg"])
                line.pack(fill="x", pady=(self.px(2), 0))
                used = 0
            chip = tk.Frame(line, bg=T["panel2"])
            chip.pack(side="left", padx=(self.px(4) if used else 0, 0))
            tk.Label(chip, text=name, fg=RARITY_COLOR.get(eng.augs.get(aid, {}).get("rarity"), T["fg"]),
                     bg=T["panel2"], font=self.f_tiny, padx=self.px(4)).pack(side="left")
            x = tk.Label(chip, text="✕", fg=T["dim"], bg=T["panel2"], font=self.f_tiny, padx=self.px(2),
                         cursor="hand2")
            x.pack(side="left")
            x.bind("<Button-1>", lambda e, a=aid: self.remove_owned(a))
            used += wpx
        plus = tk.Label(line, text=" + ", fg=T["accent"], bg=T["panel2"], font=self.f_tiny, cursor="hand2")
        plus.pack(side="left", padx=(self.px(4), 0))
        plus.bind("<Button-1>", lambda e: self._show_add_row())

    def _tips(self, wl):
        eng = self.eng
        f = self.tips_frame
        if self.cid is None:
            tk.Label(f, text="Chọn tướng (bấm tên ở trên) để xem augment nên nhắm và combo 4 mạnh nhất.",
                     fg=T["dim"], bg=T["bg"], font=self.f_tiny, wraplength=wl, justify="left",
                     anchor="w").pack(fill="x")
        else:
            d = eng.build_direction(self.owned)
            if d:
                tk.Label(f, text="Hướng: " + " · ".join(d), fg=T["accent"], bg=T["bg"], font=self.f_tiny,
                         wraplength=wl, justify="left", anchor="w").pack(fill="x")
            tg = eng.targets_by_rarity(self.cid, self.owned, self.live)
            for r in E.RARITY_ORDER:
                items = tg.get(r) or []
                if items:
                    txt = f"{E.RARITY_VN[r]}: " + " · ".join(f"{eng.aug_name(s.aid)} {s.total:+.1f}" for s in items)
                    tk.Label(f, text=txt, fg=RARITY_COLOR[r], bg=T["bg"], font=self.f_tiny, wraplength=wl,
                             justify="left", anchor="w").pack(fill="x", pady=(self.px(1), 0))
            if len(self.owned) < 4:
                combos = eng.plan_combos(self.cid, self.owned, self.live, n_combos=1)
                if combos:
                    tk.Label(f, text="Combo 4 mạnh nhất: " + " + ".join(eng.aug_name(a) for a in combos[0][1]),
                             fg=T["fg"], bg=T["bg"], font=self.f_tiny, wraplength=wl, justify="left",
                             anchor="w").pack(fill="x", pady=(self.px(3), 0))
        tk.Label(f, text=f"Dữ liệu arammeta · patch {eng.patch} · {eng.source} · "
                         f"{self.cfg.get('hotkey', 'F8')} ẩn/hiện · {self.cfg.get('ocr_hotkey', 'F9')} quét",
                 fg=T["dim"], bg=T["bg"], font=self.f_tiny, wraplength=wl, justify="left",
                 anchor="w").pack(fill="x", pady=(self.px(4), 0))

    # ------------------------------------------------------------- OCR
    def manual_scan(self):
        if not self.watcher:
            self.flash("Tự đọc augment đang tắt (\"ocr\": false trong config.json) hoặc không chạy trên Windows.")
            return
        self.watcher.save_next = os.path.join(E.user_dir(), "ocr_last.png")
        self.watcher.mode = "titles"
        self.watcher.activate(8)
        self._scan_started = time.time()
        self._ocr_published = None  # quet lai -> hien lai PICK ME du bang chon khong doi
        self.btn_scan.config(text="Đang quét…", bg=T["warn"])
        self.root.after(8500, self._scan_done, self._scan_started)

    def _scan_done(self, started):
        if started != self._scan_started:
            return
        self.btn_scan.config(text="⟳ Quét", bg=T["accent"])
        if self._last_match < started:
            if self.root.state() == "withdrawn":
                self.toggle_visible()
            if self.collapsed:
                self.toggle_collapse()
            self.flash("Không thấy bảng chọn augment. Cần: bảng chọn đang hiện, game chế độ Không viền. "
                       "Ảnh vùng vừa quét: %APPDATA%\\MayhemCombo\\ocr_last.png", 12000)

    def _on_ocr_status(self, st):
        state = (st or {}).get("state")
        if state != "error":
            return
        err = st.get("error", "")
        if err in self._ocr_errors_shown:
            return
        self._ocr_errors_shown.add(err)
        if err == "no_ocr_language":
            self.flash("Windows chưa có gói nhận dạng chữ tiếng Anh. Cài đặt → Thời gian & ngôn ngữ → "
                       "Ngôn ngữ → Thêm ngôn ngữ → English (United States), rồi mở lại app.", 20000)
        else:
            self.flash(f"Không chạy được bộ đọc màn hình: {err}", 12000)

    def _overlay_rect_in(self, fr):
        if self.capture_excluded:
            return []
        try:
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            return [(x - fr["x"] - 10, y - fr["y"] - 10, self.root.winfo_width() + 20, self.root.winfo_height() + 20)]
        except tk.TclError:
            return []

    def _on_ocr_frame(self, fr):
        res = self.eng.match_offer(fr.get("lines") or [], fr["w"], fr["h"], self._overlay_rect_in(fr))
        if res:
            key = tuple(res["slots"])
            self._ocr_miss = 0
            self._ocr_agree = self._ocr_agree + 1 if key == self._ocr_last_key else 1
            self._ocr_last_key = key
            sure = res["n"] == 3 and min(res["scores"]) >= 0.999
            if self._ocr_agree >= 2 or sure:
                self._last_match = time.time()
                self._offer_geo = (fr["x"], fr["y"], fr["w"], fr["h"])
                self._offer_pos = list(res.get("pos") or [None, None, None])
                self._badge_until = time.time() + 6  # gia han moi lan con thay bang chon
                if key != self._ocr_published:
                    self._ocr_published = key
                    log(f"OCR doc duoc: {res.get('texts')} -> {[self.eng.augs.get(a, {}).get('en') for a in key]} "
                        f"diem={res.get('scores')} khung={self._offer_geo}")
                    self._apply_ocr_offer(list(key))
                else:
                    self._refresh_badges()
            if self.watcher:
                self.watcher.mode = "titles"
                self.watcher.activate(4)  # bang chon con hien -> tiep tuc quet (bat reroll)
        else:
            self._ocr_miss += 1
            self._ocr_agree = 0
            self._ocr_last_key = None
            if self.watcher:
                self.watcher.mode = "band" if self._ocr_miss % 4 == 3 else "titles"
            if self._ocr_published and self._ocr_miss >= 3:
                self._badge_until = 0.0
                if self.badges:
                    self.badges.hide()
                if self._ocr_taken_key != self._ocr_published and any(self.offers):
                    self.flash("Bảng chọn đã đóng — bấm \"Lấy\" ở augment bạn vừa chọn.", 8000)
                self._ocr_published = None

    def _apply_ocr_offer(self, slots):
        changed = [i for i in range(3) if slots[i] != self.offers[i]]
        for i in changed:
            if slots[i] is not None or self.offers[i] not in slots:
                self.offers[i] = slots[i]
        self._offer_from_ocr = True
        self.expanded.clear()
        if self._scan_started:
            self.btn_scan.config(text="⟳ Quét", bg=T["accent"])
        if not self.badges:
            if self.root.state() == "withdrawn":
                self.toggle_visible()
            if self.collapsed:
                self.toggle_collapse()
        self.recalc()

    # ------------------------------------------------------------- PICK ME
    def badge_font(self, px: int):
        px = max(10, int(px))
        if px not in self._badge_fonts:
            self._badge_fonts[px] = tkfont.Font(family=self.font_family, size=-px, weight="bold")
        return self._badge_fonts[px]

    def _refresh_badges(self):
        if not self.badges:
            return
        ranked = self._last_ranked
        if not ranked or time.time() > self._badge_until or not self._offer_geo:
            self.badges.hide()
            return
        gx, gy, gw, gh = self._offer_geo
        defaults = OCR.default_card_centers((gx, gy, gw, gh))
        off = float(self.cfg.get("badge_offset", 0.21)) * gh
        items = []
        for i, sc in enumerate(ranked):
            if sc.aid not in self.offers:
                continue
            slot = self.offers.index(sc.aid)
            p = self._offer_pos[slot]
            cx, cy = (gx + p[0], gy + p[1]) if p else defaults[slot]
            y = max(gy + gh * 0.05, cy - off)
            if i == 0 and len(ranked) > 1:
                items.append((cx, y, f"★ PICK ME  {sc.total:+.1f}", "#111111", T["gold"], int(gh * 0.026)))
            elif sc.total < -1.0:
                items.append((cx, y, f"↻ reroll  {sc.total:+.1f}", "#111111", "#ff9e64", int(gh * 0.017)))
            else:
                items.append((cx, y, f"{sc.total:+.1f} {sc.grade}", GRADE_COLOR.get(sc.grade, T["fg"]), "#1b1e24",
                              int(gh * 0.017)))
        try:
            self.badges.show(items)
            key = tuple(self.offers)
            if key != self._badge_logged_key:
                self._badge_logged_key = key
                self.root.after(300, lambda: log("PICK ME: " + self.badges.report()))
        except Exception:  # noqa: BLE001
            log("PICK ME loi:\n" + traceback.format_exc())

    def _badge_selftest(self):
        """Hien thu nhan PICK ME 3 giay luc mo app de kiem tra nhan co hien tren man hinh khong."""
        if not self.badges:
            return
        try:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            self._selftest_until = time.time() + 3.0
            self.badges.show([(sw / 2, sh * 0.16, "★ PICK ME — nhãn hoạt động (thử 3 giây)", "#111111", T["gold"],
                               int(sh * 0.024))])
            self.root.after(400, lambda: log("Thu nhan: " + self.badges.report()))
            self.root.after(3000, self._end_selftest)
        except Exception:  # noqa: BLE001
            log("Thu nhan loi:\n" + traceback.format_exc())

    def _end_selftest(self):
        self._selftest_until = 0.0
        if self.badges and time.time() > self._badge_until:
            self.badges.hide()

    def _tick(self):
        try:
            if self.badges and self.badges.shown:
                if time.time() > self._badge_until and not self._selftest_running():
                    self.badges.hide()
                else:
                    self.badges.raise_all()  # game Khong vien co the de len -> ep lai moi giay
            if self.root.state() != "withdrawn":
                if not OCR.force_topmost(OCR.root_hwnd(self.root)):
                    self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.after(1000, self._tick)

    def _selftest_running(self):
        return time.time() < self._selftest_until

    # ------------------------------------------------------------- events
    def _pump(self):
        try:
            while True:
                tag, val = self.q.get_nowait()
                if tag == "live":
                    self._on_live(val)
                elif tag == "hotkey":
                    if val == 2:
                        self.manual_scan()
                    else:
                        self.toggle_visible()
                elif tag == "hotkey_fail":
                    self.flash(f"Không đăng ký được phím tắt {val} (app khác đang dùng?). Đổi trong config.json.")
                elif tag == "ocr_status":
                    self._on_ocr_status(val)
                elif tag == "ocr_frame":
                    self._on_ocr_frame(val)
                elif tag == "engine":
                    self._on_engine(val)
                elif tag == "champ_data" and val:
                    cid, dv, data = val
                    self.loading_champ.discard(cid)
                    if data and dv == self.eng.detail_version:
                        self.eng.set_champ_data(cid, data, fresh=True)
                        if cid == self.cid:
                            self.recalc()
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
        self.root.after(100, self._pump)

    def _on_engine(self, upd):
        if not upd:
            return
        self.eng.apply_updates(upd)
        del upd
        import gc
        gc.collect()
        self.loading_champ.clear()
        if self.cid is not None:
            self._load_champ(self.cid)
        self.recalc()

    def _on_live(self, state):
        prev = self.live
        self.live = state
        if state and state.get("alias"):
            cid = self.eng.cid_from_alias(state["alias"])
            gt = state.get("game_time") or 0
            new_game = False
            if self.last_game_time is not None and gt + 5 < self.last_game_time:
                new_game = True
            if (prev is None or not prev.get("alias")) and self.owned and cid != self.cid:
                new_game = True
            elif prev and prev.get("alias") and prev.get("alias") != state.get("alias"):
                new_game = True
            self.last_game_time = gt
            if new_game and self.cfg.get("auto_new_game", True):
                self.new_game(auto=True)
            if cid is not None and cid != self.cid:
                self.set_champ(cid)
            self._apply_aug_hints(state.get("augment_hints") or [])
            if self.watcher and (state.get("is_dead") or gt < 90):
                self.watcher.activate(3.5)  # chi quet luc dang chet (luc chon augment) hoac dau tran
            if not prev or prev.get("level") != state.get("level") or not prev.get("alias"):
                self.recalc()
        elif prev and prev.get("alias"):
            self.recalc()

    def _apply_aug_hints(self, hints):
        if not hints:
            return
        by_norm = {}
        for aid, a in self.eng.augs.items():
            by_norm[E.norm(a.get("en", ""))] = aid
            if aid in self.eng.vn_aug:
                by_norm[E.norm(self.eng.vn_aug[aid])] = aid
        ids = []
        for h in hints:
            aid = None
            if isinstance(h, int) or (isinstance(h, str) and h.isdigit()):
                aid = int(h) if int(h) in self.eng.augs else None
            elif isinstance(h, str):
                aid = by_norm.get(E.norm(h))
            if aid and aid not in ids:
                ids.append(aid)
        if ids and set(ids) != set(self.owned):
            self.owned = ids
            self.recalc()

    def on_close(self):
        try:
            if self.watcher:
                self.watcher.shutdown()
            self.cfg["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
            save_config(self.cfg)
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        App().run()
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
