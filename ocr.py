"""Mayhem Combo - tu doc 3 augment tren man hinh bang Windows OCR (client game tieng Anh).

Tiet kiem tai nguyen:
  * Worker OCR (PowerShell + Windows OCR co san) CHI chay khi can: luc ban dang chet (luc chon augment),
    dau tran, hoac khi bam phim quet (mac dinh F9). Ranh 30 giay la tu tat -> tra lai RAM.
  * Moi lan quet chi chup 1 dai nho chua 3 tieu de the augment, uu tien thap (BELOW_NORMAL) de khong lam giat game.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

IS_WIN = sys.platform.startswith("win")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER_SCRIPT = os.path.join(APP_DIR, "ocr_worker.ps1")

CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


# --------------------------------------------------------------------------- Win32 helpers

def find_game_rect():
    """(x, y, w, h, la_cua_so_game) cua vung ve game, toa do vat ly. Khong thay game -> man hinh chinh."""
    if not IS_WIN:
        return (0, 0, 1920, 1080, False)
    import ctypes
    import ctypes.wintypes as wt
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, "League of Legends (TM) Client") or u.FindWindowW("RiotWindowClass", None)
    if hwnd and not u.IsIconic(hwnd):
        r = wt.RECT()
        pt = wt.POINT(0, 0)
        if u.GetClientRect(hwnd, ctypes.byref(r)) and u.ClientToScreen(hwnd, ctypes.byref(pt)):
            if r.right > 300 and r.bottom > 300:
                return (pt.x, pt.y, r.right, r.bottom, True)
    return (0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1), False)


def exclude_from_capture(tk_root) -> bool:
    """An cua so overlay khoi anh chup man hinh (Windows 10 2004+), de OCR khong doc nham chu cua chinh app."""
    if not IS_WIN:
        return False
    try:
        return bool(_u32().SetWindowDisplayAffinity(root_hwnd(tk_root), 0x11))  # WDA_EXCLUDEFROMCAPTURE
    except Exception:  # noqa: BLE001
        return False


def _u32():
    import ctypes
    import ctypes.wintypes as wt
    u = ctypes.windll.user32
    if not getattr(u, "_mc_typed", False):
        u.GetAncestor.restype = wt.HWND
        u.GetAncestor.argtypes = [wt.HWND, wt.UINT]
        u.SetWindowPos.restype = wt.BOOL
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
        u.GetWindowLongW.restype = ctypes.c_long
        u.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
        u.SetWindowLongW.restype = ctypes.c_long
        u.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
        u.GetWindow.restype = wt.HWND
        u.GetWindow.argtypes = [wt.HWND, wt.UINT]
        u.GetTopWindow.restype = wt.HWND
        u.GetTopWindow.argtypes = [wt.HWND]
        u.IsWindowVisible.argtypes = [wt.HWND]
        u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        u.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
        u.FindWindowW.restype = wt.HWND
        u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        u._mc_typed = True
    return u


def root_hwnd(tk_win):
    if not IS_WIN:
        return None
    try:
        return _u32().GetAncestor(tk_win.winfo_id(), 2)  # GA_ROOT
    except Exception:  # noqa: BLE001
        return None


HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_FRAMECHANGED = 0x1, 0x2, 0x10, 0x40, 0x20


def force_topmost(hwnd, rect=None) -> bool:
    """Dua cua so len tren cung (ke ca tren game Khong vien) ma KHONG gianh focus."""
    if not IS_WIN or not hwnd:
        return False
    try:
        import ctypes.wintypes as wt
        u = _u32()
        if rect:
            x, y, w, h = (int(v) for v in rect)
            return bool(u.SetWindowPos(hwnd, wt.HWND(HWND_TOPMOST), x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW))
        return bool(u.SetWindowPos(hwnd, wt.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                                   SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))
    except Exception:  # noqa: BLE001
        return False


def get_rect(hwnd):
    if not IS_WIN or not hwnd:
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        r = wt.RECT()
        if _u32().GetWindowRect(hwnd, ctypes.byref(r)):
            return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:  # noqa: BLE001
        pass
    return None


def hide_window(hwnd) -> bool:
    if not IS_WIN or not hwnd:
        return False
    try:
        _u32().ShowWindow(hwnd, 0)  # SW_HIDE
        return True
    except Exception:  # noqa: BLE001
        return False


def make_badge_window(tk_win) -> bool:
    """Cua so nhan PICK ME: click xuyen qua (khong can bam the trong game), khong gianh focus,
    khong hien o Alt-Tab, va an khoi anh chup (OCR khong doc nham)."""
    if not IS_WIN:
        return False
    try:
        u = _u32()
        hwnd = root_hwnd(tk_win)
        GWL_EXSTYLE = -20
        ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        # WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        ex |= 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
        u.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED | 0x4)  # 0x4 = NOZORDER
        u.SetWindowDisplayAffinity(hwnd, 0x11)
        return True
    except Exception:  # noqa: BLE001
        return False


def game_hwnd():
    if not IS_WIN:
        return None
    try:
        u = _u32()
        return u.FindWindowW(None, "League of Legends (TM) Client") or u.FindWindowW("RiotWindowClass", None)
    except Exception:  # noqa: BLE001
        return None


def window_report(hwnds: dict) -> str:
    """Chan doan: vi tri, hien/an va thu tu lop (z-order) cua cac cua so so voi game."""
    if not IS_WIN:
        return "not windows"
    try:
        import ctypes
        import ctypes.wintypes as wt
        u = _u32()
        targets = dict(hwnds)
        g = game_hwnd()
        if g:
            targets["game"] = g
        want = {int(v): k for k, v in targets.items() if v}
        order = {}
        h = u.GetTopWindow(None)
        i = 0
        while h and i < 3000 and len(order) < len(want):
            if int(h) in want:
                order[want[int(h)]] = i
            h = u.GetWindow(h, 2)  # GW_HWNDNEXT
            i += 1
        parts = []
        for name, hw in targets.items():
            if not hw:
                continue
            r = wt.RECT()
            u.GetWindowRect(hw, ctypes.byref(r))
            ex = u.GetWindowLongW(hw, -20)
            parts.append(f"{name}: z={order.get(name, '?')} vis={u.IsWindowVisible(hw)} "
                         f"rect=({r.left},{r.top},{r.right - r.left}x{r.bottom - r.top}) topmost={bool(ex & 8)}")
        return " | ".join(parts)
    except Exception as e:  # noqa: BLE001
        return f"report error: {e}"


def default_card_centers(rect) -> list:
    """Vi tri mac dinh (man hinh) cua tieu de 3 the augment khi chua co toa do OCR."""
    x, y, w, h = rect[:4]
    return [(x + w / 2 + k * 0.34 * h, y + 0.40 * h) for k in (-1, 0, 1)]


# --------------------------------------------------------------------------- worker process

class OcrWorker:
    def __init__(self, lang: str, log):
        self.lang = lang
        self.log = log
        self.proc = None
        self.lines: queue.Queue = queue.Queue()
        self.info: dict = {}

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, timeout: float = 20.0) -> dict:
        self.stop()
        if not IS_WIN:
            return {"ok": False, "error": "not_windows"}
        if not os.path.exists(WORKER_SCRIPT):
            return {"ok": False, "error": "missing_worker"}
        args = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", WORKER_SCRIPT, "-Lang", self.lang]
        try:
            self.proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except Exception as e:  # noqa: BLE001
            self.proc = None
            return {"ok": False, "error": f"không chạy được PowerShell: {e}"}
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, args=(self.proc, self.lines), daemon=True).start()
        first = self._read(timeout)
        if not first or not first.get("ready"):
            self.stop()
            return first or {"ok": False, "error": "worker_timeout"}
        self.info = first
        return first

    @staticmethod
    def _reader(proc, q):
        try:
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("{"):
                    q.put(line)
        except Exception:  # noqa: BLE001
            pass
        q.put(None)

    def _read(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if line is None:
            return None
        try:
            return json.loads(line)
        except Exception:  # noqa: BLE001
            return None

    def request(self, obj: dict, timeout: float = 8.0):
        if not self.alive():
            return None
        try:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()
        except Exception:  # noqa: BLE001
            self.stop()
            return None
        res = self._read(timeout)
        if res is None:
            self.stop()  # treo -> tat, lan sau mo lai
        return res

    def stop(self):
        p = self.proc
        self.proc = None
        if p is None:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.write('{"cmd":"quit"}\n')
                    p.stdin.flush()
                    p.wait(timeout=1.5)
                except Exception:  # noqa: BLE001
                    pass
            if p.poll() is None:
                p.kill()
        except Exception:  # noqa: BLE001
            pass


class OcrWatcher(threading.Thread):
    """Luong nen: khi duoc 'kich hoat' thi quet man hinh moi ~0.7s va gui ket qua ve app."""

    def __init__(self, out_q: queue.Queue, lang: str, log, interval: float = 0.7, idle_stop: float = 30.0):
        super().__init__(daemon=True)
        self.out_q = out_q
        self.log = log
        self.worker = OcrWorker(lang, log)
        self.interval = interval
        self.idle_stop = idle_stop
        self.active_until = 0.0
        self.mode = "titles"
        self.save_next = None
        self.disabled = False
        self._last_active = 0.0
        self._wake = threading.Event()
        self._fail_until = 0.0

    def activate(self, seconds: float):
        if self.disabled:
            return
        until = time.time() + seconds
        if until > self.active_until:
            self.active_until = until
        self._wake.set()

    def run(self):
        while True:
            now = time.time()
            if self.disabled:
                self.worker.stop()
                self._wake.wait(5)
                self._wake.clear()
                continue
            if now < self.active_until and now >= self._fail_until:
                self._last_active = now
                if not self.worker.alive():
                    self.out_q.put(("ocr_status", {"state": "starting"}))
                    info = self.worker.start()
                    if not info.get("ok"):
                        err = info.get("error") or "lỗi không rõ"
                        self.log(f"OCR worker: {err}")
                        self.out_q.put(("ocr_status", {"state": "error", "error": err}))
                        if err in ("no_ocr_language", "not_windows", "missing_worker"):
                            self.disabled = True
                        else:
                            self._fail_until = time.time() + 30
                        continue
                    self.out_q.put(("ocr_status", {"state": "ready", "lang": info.get("lang")}))
                x, y, w, h, is_game = find_game_rect()
                req = {"cmd": "scan", "x": x, "y": y, "w": w, "h": h, "mode": self.mode}
                if self.save_next:
                    req["save"], self.save_next = self.save_next, None
                t0 = time.time()
                res = self.worker.request(req)
                if res and res.get("ok"):
                    self.out_q.put(("ocr_frame", {"x": x, "y": y, "w": w, "h": h, "game": is_game,
                                                  "mode": res.get("mode"), "ms": res.get("ms"),
                                                  "lines": res.get("lines") or []}))
                elif res is not None:
                    self.log(f"OCR scan: {res.get('error')}")
                spent = time.time() - t0
                self._wake.wait(max(0.15, self.interval - spent))
                self._wake.clear()
            else:
                if self.worker.alive() and now - self._last_active > self.idle_stop:
                    self.worker.stop()
                    self.out_q.put(("ocr_status", {"state": "sleep"}))
                self._wake.wait(1.0)
                self._wake.clear()

    def shutdown(self):
        self.disabled = True
        self.worker.stop()
