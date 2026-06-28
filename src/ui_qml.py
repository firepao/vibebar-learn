from __future__ import annotations
import ctypes, os, queue, sys, threading, time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtWidgets import QApplication

from models import (
    SessionsModel, IslandBridge,
    read_state, _save_state, _acquire_lock, _release_lock, _age_sec,
    STATUS_RUNNING, STATUS_IDLE,
    FOUR_HOURS_SEC, IDLE_PURGE_SEC, STALE_RUNNING_SEC,
    load_ui_config, _save_card_order,
)
from win32 import (
    ensure_on_current_desktop, get_primary_work_area,
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE,
    GetWindowLongPtr, SetWindowLongPtr,
    DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE,
    set_island_mask, get_foreground_snapshot,
)

_BASE_ISLAND_W = 280
_BASE_COLLAPSED_H = 20


def _get_ui_scale() -> float:
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        win_scale = max(dpi, 96) / 96.0
        return 1.0 + (win_scale - 1.0) * 0.5  # soften: 150%→1.25, 200%→1.5
    except Exception:
        return 1.0


FINISH_NOTIFICATION_TEXT = {
    "completed": "Task complete",
    "interrupted": "Task interrupted",
    "stale": "Task interrupted",
}


def _finish_event_payload(has_seen: bool, last_seen: str, finished_at: str, reason: str | None) -> tuple[bool, str, str]:
    normalized = str(reason or "").strip() or "completed"
    text = FINISH_NOTIFICATION_TEXT.get(normalized, FINISH_NOTIFICATION_TEXT["completed"])
    should_emit = bool(has_seen and finished_at and finished_at != last_seen)
    return should_emit, normalized, text


def _finish_notice_payload(
    has_seen: bool,
    last_seen: str,
    finished_at: str,
    sess: dict,
) -> tuple[bool, str, str, str, str, str]:
    should_emit, reason, title = _finish_event_payload(
        has_seen, last_seen, finished_at, sess.get("finish_reason")
    )
    cwd_name = str(sess.get("cwd_name") or "").strip()
    if not cwd_name:
        cwd = str(sess.get("cwd") or "").strip()
        cwd_name = Path(cwd).name or cwd
    prompt = str(sess.get("last_prompt") or "").strip()
    source = str(sess.get("source") or "claude").strip() or "claude"
    return should_emit, reason, title, cwd_name, prompt, source


class VibeBarApp:
    def __init__(self):
        self.qt = QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)

        sf = _get_ui_scale()
        self._island_w = int(_BASE_ISLAND_W * sf)
        self._collapsed_h = int(_BASE_COLLAPSED_H * sf)
        self._ui_scale = sf

        self._cmd_queue: queue.Queue = queue.Queue()
        self._state_queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()

        self.model = SessionsModel()
        self.bridge = IslandBridge(self.model, self._cmd_queue)
        self.bridge._island_w_logical = self._island_w
        self.bridge._island_h = self._collapsed_h

        self._last_finished_at: dict[str, str] = {}
        self._seen_finished_sids: set[str] = set()
        self._last_attention_at: dict[str, str] = {}
        self._last_session_prompt_at: dict[str, str] = {}
        self._visible_sessions: dict[str, dict] = {}
        self._last_phys_wa = None
        self._own_hwnd = 0
        self._overlay_hwnd = 0
        self._last_overlay_sid = ""
        self._reposition_needed = False
        self._flash_timers: dict[str, QTimer] = {}
        self._saved_cwd_order: list = load_ui_config().get("card_order") or []
        self._last_cwd_order: list = list(self._saved_cwd_order)
        self._initial_order_restored: bool = False

        self._engine = QQmlApplicationEngine()
        ctx = self._engine.rootContext()
        ctx.setContextProperty("sessionsModel", self.model)
        ctx.setContextProperty("bridge", self.bridge)
        ctx.setContextProperty("scaleFactor", self._ui_scale)

        qml = Path(__file__).with_name("island.qml")
        self._engine.load(str(qml))

        roots = self._engine.rootObjects()
        if not roots:
            sys.exit(1)
        self._win = roots[0]
        self.bridge._win = self._win
        self._position_window()
        QTimer.singleShot(200, self._setup_win32)

        overlay_qml = Path(__file__).with_name("agent_overlay.qml")
        self._engine.load(str(overlay_qml))
        roots = self._engine.rootObjects()
        self._overlay = roots[1] if len(roots) > 1 else None
        if self._overlay is not None:
            self._overlay.setProperty("visible", False)
            QTimer.singleShot(250, self._setup_overlay_win32)

        self._consume_timer = QTimer()
        self._consume_timer.setInterval(100)
        self._consume_timer.timeout.connect(self._consume)
        self._consume_timer.start()

        self._overlay_timer = QTimer()
        self._overlay_timer.setInterval(250)
        self._overlay_timer.timeout.connect(self._update_agent_overlay)
        self._overlay_timer.start()

        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def run(self) -> int:
        code = self.qt.exec()
        self._stop_event.set()
        return code

    # ── window setup ─────────────────────────────────────────────────────────

    def _position_window(self) -> None:
        screen = QApplication.primaryScreen()
        ag = screen.availableGeometry()
        saved_x = load_ui_config().get("island_x")
        default_x = ag.left() + (ag.width() - self._island_w) // 2
        x = max(ag.left(), min(int(saved_x), ag.right() - self._island_w)) if saved_x is not None else default_x
        self._win.setProperty("x", x)
        self._win.setProperty("y", ag.top())
        self._win.setProperty("width", self._island_w)
        self._win.setProperty("height", ag.height())
        self.bridge._window_h_logical = ag.height()
        if self._own_hwnd:
            set_island_mask(self._own_hwnd, ag.height(), self.bridge._island_h, self._island_w)

    def _setup_win32(self) -> None:
        hwnd = int(self._win.winId())
        self._own_hwnd = hwnd
        self.bridge._own_hwnd = hwnd
        ex = GetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE)
        SetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE,
                         (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        color = ctypes.c_uint(DWMWA_COLOR_NONE)
        DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_BORDER_COLOR,
                              ctypes.byref(color), ctypes.sizeof(color))
        set_island_mask(hwnd, self.bridge._window_h_logical, self._collapsed_h, self._island_w)

    def _setup_overlay_win32(self) -> None:
        if self._overlay is None:
            return
        hwnd = int(self._overlay.winId())
        self._overlay_hwnd = hwnd
        ex = GetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE)
        SetWindowLongPtr(
            wintypes.HWND(hwnd),
            GWL_EXSTYLE,
            (ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW,
        )
        color = ctypes.c_uint(DWMWA_COLOR_NONE)
        DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_BORDER_COLOR,
            ctypes.byref(color),
            ctypes.sizeof(color),
        )

    # ── state consumption ─────────────────────────────────────────────────────

    def _consume(self) -> None:
        if self._reposition_needed:
            self._reposition_needed = False
            self._position_window()
        try:
            state = self._state_queue.get_nowait()
            self._apply_state(state)
        except queue.Empty:
            pass

    def _apply_state(self, state: dict) -> None:
        all_sessions = state.get("sessions", {}) or {}
        now_dt = datetime.now()

        candidates: dict = {}
        running_codex_parent_sids: set = set()
        for sid, s in all_sessions.items():
            if s.get("source") == "codex" and s.get("status") == STATUS_RUNNING and s.get("parent_sid"):
                running_codex_parent_sids.add(s["parent_sid"])
            if (s.get("is_primary") and not s.get("user_closed")
                    and (s.get("status") == STATUS_RUNNING or _age_sec(s, now_dt) <= FOUR_HOURS_SEC)
                    and not s.get("is_rescue_agent")
                    and not str(s.get("last_prompt") or "").lstrip().startswith(("--wait", "<task>"))):
                candidates[sid] = s

        sessions = {}
        for sid, s in candidates.items():
            if (s.get("source") != "codex"
                    and s.get("status") == STATUS_IDLE
                    and s.get("active_subagent_count", 0) == 0
                    and not s.get("active_bash")
                    and sid in running_codex_parent_sids):
                s = dict(s)
                s["active_subagent_count"] = 1
            sessions[sid] = s

        cur_order = self.model.get_order()
        sid_order_set: set = set(cur_order) & set(sessions)
        sid_order = [sid for sid in cur_order if sid in sid_order_set]
        for sid in sessions:
            if sid not in sid_order_set:
                sid_order.append(sid)
                sid_order_set.add(sid)

        saved_cwds = self._saved_cwd_order if not self._initial_order_restored else self.model.get_cwd_order()

        grouped: dict = {}
        no_cwd: list = []
        for sid in sid_order:
            cwd = str(sessions[sid].get("cwd") or "")
            if cwd:
                grouped.setdefault(cwd, []).append(sid)
            else:
                no_cwd.append(sid)

        order: list = []
        seen_saved: set = set()
        for cwd in saved_cwds:
            if not isinstance(cwd, str) or cwd in seen_saved:
                continue
            seen_saved.add(cwd)
            order.extend(grouped.pop(cwd, []))
        for sids in grouped.values():
            order.extend(sids)
        order.extend(no_cwd)

        if not self.bridge._is_dragging:
            self.model.update_sessions(sessions, order)
            self._visible_sessions = dict(sessions)
            if not self._initial_order_restored and sessions:
                self._initial_order_restored = True
            new_cwd_order = self.model.get_cwd_order()
            if new_cwd_order != self._last_cwd_order:
                _save_card_order(new_cwd_order)
                self._saved_cwd_order = new_cwd_order
                self._last_cwd_order = new_cwd_order

        for sid, sess in sessions.items():
            self._capture_session_jump_target(sid, sess)
            self._capture_attention_jump_target(sid, sess)
            finished_at = sess.get("finished_at") or ""
            last_seen = self._last_finished_at.get(sid, "")
            has_seen = sid in self._seen_finished_sids
            should_notify, reason, title, cwd_name, prompt, source = _finish_notice_payload(
                has_seen, last_seen, finished_at, sess
            )
            if finished_at != last_seen:
                self._last_finished_at[sid] = finished_at
                if should_notify:
                    self._flash_done(sid)
                    self.bridge.sessionFinished.emit(
                        sid, reason, title, cwd_name, prompt, source
                    )
            self._seen_finished_sids.add(sid)

        for sid in list(self._last_finished_at):
            if sid not in sessions:
                self._last_finished_at.pop(sid, None)
                self._seen_finished_sids.discard(sid)
                self._last_attention_at.pop(sid, None)
                self._last_session_prompt_at.pop(sid, None)
        for sid in list(self._seen_finished_sids):
            if sid not in sessions:
                self._seen_finished_sids.discard(sid)

    def _session_overlay_state(self, sess: dict) -> str:
        if sess.get("status") == STATUS_RUNNING:
            return "running"
        if sess.get("active_subagent_count", 0) > 0 or sess.get("active_bash"):
            return "background"
        return "idle"

    def _is_overlay_active(self, sess: dict) -> bool:
        return bool(
            sess.get("needs_attention")
            or sess.get("status") == STATUS_RUNNING
            or sess.get("active_subagent_count", 0) > 0
            or sess.get("active_bash")
        )

    def _best_overlay_session(self) -> tuple[str, dict] | None:
        order = self.model.get_order()
        rows = self._visible_sessions
        candidates = [(sid, rows[sid]) for sid in order if sid in rows and self._is_overlay_active(rows[sid])]
        if not candidates:
            candidates = [(sid, s) for sid, s in rows.items() if self._is_overlay_active(s)]
        if not candidates:
            return None

        def priority(item: tuple[str, dict]) -> int:
            _sid, sess = item
            if sess.get("needs_attention"):
                return 0
            if sess.get("status") == STATUS_RUNNING:
                return 1
            return 2

        candidates.sort(key=priority)
        return candidates[0]

    def _window_matches_session(self, snap: dict, sid: str, sess: dict) -> int:
        hwnd = int(snap.get("hwnd") or 0)
        title = str(snap.get("title") or "").lower()
        if not hwnd:
            return 0
        for key in ("attention_jump_hwnd", "session_jump_hwnd"):
            target_hwnd = int(sess.get(key) or 0)
            if target_hwnd and target_hwnd == hwnd:
                return 100
        cwd_name = str(sess.get("cwd_name") or "").strip().lower()
        cwd = str(sess.get("cwd") or "").strip()
        cwd_base = Path(cwd).name.lower() if cwd else ""
        names = [n for n in (cwd_name, cwd_base) if n]
        if any(n in title for n in names):
            score = 60
            source = str(sess.get("source") or "").lower()
            if source and source in title:
                score += 10
            return score
        return 0

    def _is_foreground_agent_page(self, snap: dict) -> bool:
        if not snap:
            return False
        hwnd = int(snap.get("hwnd") or 0)
        if hwnd and hwnd == self._overlay_hwnd:
            return False
        title = str(snap.get("title") or "").lower()
        if "codex" in title or "claude" in title:
            return True
        if any(self._window_matches_session(snap, sid, sess) for sid, sess in self._visible_sessions.items()):
            return True
        terminal_host = any(
            marker in title
            for marker in ("terminal", "powershell", "command prompt", "cmd.exe", "windows terminal")
        )
        return terminal_host and len([s for s in self._visible_sessions.values() if self._is_overlay_active(s)]) == 1

    def _position_agent_overlay(self) -> None:
        if self._overlay is None or bool(self._overlay.property("dragging")):
            return
        screen = QApplication.primaryScreen()
        ag = screen.availableGeometry()
        width = int(self._overlay.property("width") or round(76 * self._ui_scale))
        height = int(self._overlay.property("height") or width)
        margin = int(18 * self._ui_scale)
        cfg = load_ui_config()
        saved_x = cfg.get("agent_overlay_x")
        saved_y = cfg.get("agent_overlay_y")
        default_x = ag.right() - width - margin + 1
        default_y = ag.bottom() - height - margin + 1
        try:
            x = int(saved_x) if saved_x is not None else default_x
            y = int(saved_y) if saved_y is not None else default_y
        except Exception:
            x, y = default_x, default_y
        x = max(ag.left(), min(x, ag.right() - width + 1))
        y = max(ag.top(), min(y, ag.bottom() - height + 1))
        self._overlay.setProperty("x", x)
        self._overlay.setProperty("y", y)

    def _update_agent_overlay(self) -> None:
        if self._overlay is None:
            return
        if bool(self._overlay.property("dragging")):
            return
        best = self._best_overlay_session()
        if not best:
            self._overlay.setProperty("visible", False)
            self._last_overlay_sid = ""
            return
        snap = get_foreground_snapshot(self._own_hwnd, os.getpid())
        if self._is_foreground_agent_page(snap):
            self._overlay.setProperty("visible", False)
            self._last_overlay_sid = ""
            return
        sid, sess = best
        self._position_agent_overlay()
        self._overlay.setProperty("sid", sid)
        self._overlay.setProperty("agentSource", str(sess.get("source") or "claude"))
        self._overlay.setProperty("agentState", self._session_overlay_state(sess))
        self._overlay.setProperty("needsAttention", bool(sess.get("needs_attention")))
        self._overlay.setProperty("visible", True)
        self._last_overlay_sid = sid

    def _capture_session_jump_target(self, sid: str, sess: dict) -> None:
        if not self._is_overlay_active(sess):
            self._last_session_prompt_at.pop(sid, None)
            return
        marker = str(sess.get("prompt_at") or sess.get("last_update") or "")
        if not marker or self._last_session_prompt_at.get(sid) == marker:
            return
        self._last_session_prompt_at[sid] = marker
        snap = get_foreground_snapshot(self._own_hwnd, os.getpid())
        if not snap or int(snap.get("hwnd") or 0) == self._overlay_hwnd:
            return
        fd = _acquire_lock()
        if fd is None:
            return
        try:
            state = read_state()
            target = state.get("sessions", {}).get(sid)
            if not target:
                return
            target_marker = str(target.get("prompt_at") or target.get("last_update") or "")
            if target_marker != marker:
                return
            target["session_jump_hwnd"] = int(snap.get("hwnd") or 0)
            target["session_jump_title"] = str(snap.get("title") or "")
            target["session_jump_pid"] = int(snap.get("pid") or 0)
            _save_state(state)
        finally:
            _release_lock(fd)
    def _capture_attention_jump_target(self, sid: str, sess: dict) -> None:
        if not sess.get("needs_attention"):
            self._last_attention_at.pop(sid, None)
            return
        attention_at = str(sess.get("attention_at") or "")
        if not attention_at or self._last_attention_at.get(sid) == attention_at:
            return
        self._last_attention_at[sid] = attention_at
        if sess.get("attention_jump_hwnd"):
            return
        snap = get_foreground_snapshot(self._own_hwnd, os.getpid())
        if not snap:
            return
        fd = _acquire_lock()
        if fd is None:
            return
        try:
            state = read_state()
            target = state.get("sessions", {}).get(sid)
            if not target or not target.get("needs_attention"):
                return
            if str(target.get("attention_at") or "") != attention_at:
                return
            target["attention_jump_hwnd"] = int(snap.get("hwnd") or 0)
            target["attention_jump_title"] = str(snap.get("title") or "")
            target["attention_jump_pid"] = int(snap.get("pid") or 0)
            _save_state(state)
        finally:
            _release_lock(fd)

    def _flash_done(self, sid: str) -> None:
        old = self._flash_timers.pop(sid, None)
        if old: old.stop(); old.deleteLater()
        count = [6]

        def step():
            n = count[0]; count[0] -= 1
            if n <= 0 or sid not in self.model.get_order():
                self.model.set_bg(sid, "#0d0f14")
                t = self._flash_timers.pop(sid, None)
                if t: t.stop(); t.deleteLater()
                return
            from models import FLASH_COLOR, SURFACE
            self.model.set_bg(sid, FLASH_COLOR if n % 2 == 0 else SURFACE)

        t = QTimer()
        t.setInterval(200)
        t.timeout.connect(step)
        t.start()
        self._flash_timers[sid] = t

    # ── worker thread ─────────────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        last_state = last_wa = 0.0
        startup_done = False
        while not self._stop_event.is_set():
            try:
                while True:
                    op, payload = self._cmd_queue.get_nowait()
                    if op == "close_session":
                        self._do_close_sid(payload)
            except queue.Empty:
                pass

            self._worker_follow_desktop()

            now = time.monotonic()
            if now - last_wa >= 1.0:
                try:
                    wa = get_primary_work_area()
                    if wa != self._last_phys_wa:
                        self._last_phys_wa = wa
                        self._reposition_needed = True
                except Exception:
                    pass
                last_wa = now

            if not startup_done:
                try: self._do_purge_stale()
                except Exception: pass
                startup_done = True

            if now - last_state >= 0.25:
                try:
                    s = read_state()
                    try: self._state_queue.get_nowait()
                    except queue.Empty: pass
                    self._state_queue.put_nowait(s)
                except Exception:
                    pass
                last_state = now

            self._stop_event.wait(0.1)

    def _worker_follow_desktop(self) -> None:
        own = self._own_hwnd
        if not own: return
        try:
            fg = int(ctypes.windll.user32.GetForegroundWindow() or 0)
            if fg and fg != own:
                ensure_on_current_desktop(fg, own)
        except Exception:
            pass

    def _do_close_sid(self, sid: str) -> None:
        fd = _acquire_lock()
        if fd is None: return
        try:
            state = read_state()
            if sid in state.get("sessions", {}):
                state["sessions"][sid]["user_closed"] = True
                _save_state(state)
        finally:
            _release_lock(fd)

    def _do_purge_stale(self) -> None:
        fd = _acquire_lock()
        if fd is None: return
        try:
            state = read_state()
            sessions = state.get("sessions", {})
            now = datetime.now(); changed = False
            to_del = []
            for sid, s in sessions.items():
                age = _age_sec(s, now)
                if s.get("status") == "running" and age > FOUR_HOURS_SEC and s.get("is_primary"):
                    s["status"] = "idle"
                    s.setdefault("finished_at", s.get("last_update"))
                    changed = True
                elif s.get("status") == "running" and age > STALE_RUNNING_SEC and not s.get("is_primary"):
                    s["status"] = "idle"
                    s.setdefault("finished_at", s.get("last_update"))
                    changed = True
                elif s.get("status") == "idle" and age > IDLE_PURGE_SEC:
                    to_del.append(sid); changed = True
            for sid in to_del:
                del sessions[sid]
            if changed: _save_state(state)
        finally:
            _release_lock(fd)


if __name__ == "__main__":
    app = VibeBarApp()
    sys.exit(app.run())
