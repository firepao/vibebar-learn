# VibeBar Finish Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an in-island finish notification that flashes the completed card, auto-expands the island, shows a short completion/interruption pill, and auto-collapses when the user is not interacting.

**Architecture:** Keep the implementation on the existing `finished_at` flow. `hook.py` records a `finish_reason`, `ui_qml.py` maps new finish timestamps to a bridge signal, and `island.qml` reacts by showing a short overlay pill while preserving existing hover and drag behavior.

**Tech Stack:** Python 3, PyQt6/QML, existing `test_scenarios.py` script, existing JSON state file under `%LOCALAPPDATA%\VibeBar\state.json`.

---

## File Structure

- Modify `src/hook.py`: add `finish_reason` state for `Stop`, `StopFailure`, stale cleanup, and clear it on `UserPromptSubmit`.
- Modify `src/ui_qml.py`: add a pure helper for finish notification payloads, emit a bridge signal from the existing `_last_finished_at` observer, and keep `_flash_done()` as the visual pulse.
- Modify `src/models.py`: add `IslandBridge.sessionFinished = pyqtSignal(str, str, str)`.
- Modify `src/island.qml`: listen for `sessionFinished`, auto-expand, render a compact notification pill, and auto-collapse only when hover/drag is inactive.
- Modify `test_scenarios.py`: add automated tests for hook state and the finish payload helper. QML behavior gets manual verification because this repo has no QML test harness.

Current known dirty files before implementation:

- `install.py` has unrelated local changes from earlier setup work. Do not stage it unless the user explicitly asks.
- `.superpowers/` may contain local brainstorming artifacts. Do not stage it.

---

### Task 1: Record Finish Reasons in Hook State

**Files:**
- Modify: `test_scenarios.py`
- Modify: `src/hook.py`

- [ ] **Step 1: Write the failing lifecycle tests**

In `test_scenarios.py`, extend the existing lifecycle checks near the first `UserPromptSubmit`, `Stop`, and `StopFailure` assertions.

After:

```python
check("UserPromptSubmit: user_closed 娓呴櫎", "user_closed" not in s)
```

add:

```python
check("UserPromptSubmit: finish_reason cleared", "finish_reason" not in s)
```

After:

```python
check("Stop: finished_at 有值", bool(s.get("finished_at")))
```

add:

```python
check("Stop: finish_reason=completed", s.get("finish_reason") == "completed", s.get("finish_reason"))
```

After:

```python
check("StopFailure: status=idle", s.get("status") == "idle")
```

add:

```python
check("StopFailure: finish_reason=interrupted", s.get("finish_reason") == "interrupted", s.get("finish_reason"))
```

- [ ] **Step 2: Write the failing stale cleanup test**

In `test_scenarios.py`, find the stale cleanup section where a non-primary running session older than 10 minutes is idled:

```python
check("非primary running >10min → idle", s.get("status") == "idle")
```

Immediately after it, add:

```python
check("非primary running >10min → finish_reason=stale",
      s.get("finish_reason") == "stale", s.get("finish_reason"))
```

Find the primary running session older than 4 hours check:

```python
check("primary running >4h → idle", s.get("status") == "idle")
```

Immediately after it, add:

```python
check("primary running >4h → finish_reason=stale",
      s.get("finish_reason") == "stale", s.get("finish_reason"))
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
python test_scenarios.py
```

Expected: nonzero exit. The new labels fail because `finish_reason` is not yet written:

```text
Stop: finish_reason=completed
StopFailure: finish_reason=interrupted
finish_reason=stale
```

- [ ] **Step 4: Implement minimal hook state changes**

In `src/hook.py`, update `cleanup_stale_sessions()` inside the branch that idles a stale running session.

Change:

```python
        if sess.get("status") == "running" and age > stale_thresh:
            sess["status"] = "idle"
            sess.pop("needs_attention", None)
            if not sess.get("finished_at"):
                sess["finished_at"] = sess.get("last_update")
```

to:

```python
        if sess.get("status") == "running" and age > stale_thresh:
            sess["status"] = "idle"
            sess["finish_reason"] = "stale"
            sess.pop("needs_attention", None)
            if not sess.get("finished_at"):
                sess["finished_at"] = sess.get("last_update")
```

In the `UserPromptSubmit` branch, after:

```python
            sess["finished_at"] = None
```

add:

```python
            sess.pop("finish_reason", None)
```

In the `Stop` / `StopFailure` branch, change:

```python
            sess["status"] = "idle"
            sess["finished_at"] = _now_iso()
            sess["active_bash"] = False
```

to:

```python
            sess["status"] = "idle"
            sess["finished_at"] = _now_iso()
            sess["finish_reason"] = "interrupted" if event == "StopFailure" else "completed"
            sess["active_bash"] = False
```

- [ ] **Step 5: Run tests to verify Task 1 passes**

Run:

```powershell
python test_scenarios.py
```

Expected: exit code `0`. The new finish reason checks pass.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add test_scenarios.py src/hook.py
git commit -m "feat: record finish reasons"
```

Expected: commit contains only `test_scenarios.py` and `src/hook.py`.

---

### Task 2: Map Finish Events to Bridge Notifications

**Files:**
- Modify: `test_scenarios.py`
- Modify: `src/models.py`
- Modify: `src/ui_qml.py`

- [ ] **Step 1: Write the failing payload helper tests**

In `test_scenarios.py`, add this import after the existing `from models import (...)` block:

```python
import ui_qml
```

At the end of `test_scenarios.py`, before the final results summary block, add this new section:

```python
# ════════════════════════════════════════════════════════════════════════════════
# 16. Finish notification payload
# ════════════════════════════════════════════════════════════════════════════════
section("16. Finish notification payload")

payload_fn = getattr(ui_qml, "_finish_event_payload", None)
check("_finish_event_payload exists", callable(payload_fn))

if callable(payload_fn):
    should_emit, reason, text = payload_fn("", "2026-06-02T10:00:00", "completed")
    check("initial historical finish does not notify", should_emit is False)
    check("initial historical finish normalizes completed",
          reason == "completed" and text == "Task complete", (reason, text))

    should_emit, reason, text = payload_fn("2026-06-02T09:59:00", "2026-06-02T10:00:00", "completed")
    check("new completed finish notifies",
          should_emit is True and reason == "completed" and text == "Task complete",
          (should_emit, reason, text))

    should_emit, reason, text = payload_fn("2026-06-02T09:59:00", "2026-06-02T10:00:00", "interrupted")
    check("new interrupted finish notifies",
          should_emit is True and reason == "interrupted" and text == "Task interrupted",
          (should_emit, reason, text))

    should_emit, reason, text = payload_fn("2026-06-02T09:59:00", "2026-06-02T10:00:00", "stale")
    check("new stale finish uses interrupted text",
          should_emit is True and reason == "stale" and text == "Task interrupted",
          (should_emit, reason, text))

    should_emit, reason, text = payload_fn("2026-06-02T09:59:00", "2026-06-02T10:00:00", "")
    check("missing reason defaults to completed",
          should_emit is True and reason == "completed" and text == "Task complete",
          (should_emit, reason, text))

    should_emit, reason, text = payload_fn("2026-06-02T10:00:00", "2026-06-02T10:00:00", "completed")
    check("same finished_at does not notify", should_emit is False)
else:
    check("completed text mapping", False, "_finish_event_payload missing")
    check("interrupted text mapping", False, "_finish_event_payload missing")
    check("stale text mapping", False, "_finish_event_payload missing")
    check("same finished_at suppression", False, "_finish_event_payload missing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python test_scenarios.py
```

Expected: nonzero exit. `_finish_event_payload exists` fails because the helper is missing.

- [ ] **Step 3: Add the bridge signal**

In `src/models.py`, update `IslandBridge`.

Change:

```python
class IslandBridge(QObject):
    collapseRequested = pyqtSignal()
```

to:

```python
class IslandBridge(QObject):
    collapseRequested = pyqtSignal()
    sessionFinished = pyqtSignal(str, str, str)
```

- [ ] **Step 4: Add the finish payload helper**

In `src/ui_qml.py`, add this helper below `_get_ui_scale()` and before `class VibeBarApp`:

```python
FINISH_NOTIFICATION_TEXT = {
    "completed": "Task complete",
    "interrupted": "Task interrupted",
    "stale": "Task interrupted",
}


def _finish_event_payload(last_seen: str, finished_at: str, reason: str | None) -> tuple[bool, str, str]:
    normalized = str(reason or "").strip() or "completed"
    text = FINISH_NOTIFICATION_TEXT.get(normalized, FINISH_NOTIFICATION_TEXT["completed"])
    should_emit = bool(finished_at and last_seen and finished_at != last_seen)
    return should_emit, normalized, text
```

- [ ] **Step 5: Emit the bridge signal from the existing finish observer**

In `src/ui_qml.py`, replace the existing finish observer block:

```python
        for sid, sess in sessions.items():
            finished_at = sess.get("finished_at") or ""
            last_seen = self._last_finished_at.get(sid, "")
            if finished_at and finished_at != last_seen:
                self._last_finished_at[sid] = finished_at
                if last_seen:
                    self._flash_done(sid)
```

with:

```python
        for sid, sess in sessions.items():
            finished_at = sess.get("finished_at") or ""
            last_seen = self._last_finished_at.get(sid, "")
            should_notify, reason, text = _finish_event_payload(
                last_seen, finished_at, sess.get("finish_reason")
            )
            if finished_at and finished_at != last_seen:
                self._last_finished_at[sid] = finished_at
                if should_notify:
                    self._flash_done(sid)
                    self.bridge.sessionFinished.emit(sid, reason, text)
```

- [ ] **Step 6: Run tests to verify Task 2 passes**

Run:

```powershell
python test_scenarios.py
```

Expected: exit code `0`. The payload helper tests pass.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
git add test_scenarios.py src/models.py src/ui_qml.py
git commit -m "feat: emit finish notifications"
```

Expected: commit contains only `test_scenarios.py`, `src/models.py`, and `src/ui_qml.py`.

---

### Task 3: Add the QML Auto-Expand Notification Pill

**Files:**
- Modify: `src/island.qml`

- [ ] **Step 1: Add notification state properties**

In `src/island.qml`, inside the `Rectangle { id: island ... }` property block, after:

```qml
        property int  expandedH: bodyPadding * 2 + visibleRows * slotH
```

add:

```qml
        property string notifySid: ""
        property string notifyText: ""
        property string notifyReason: "completed"
        property bool notifyVisible: notifyText.length > 0
```

- [ ] **Step 2: Add the bridge signal handler**

In `src/island.qml`, extend the existing `Connections { target: bridge ... }` block near the top.

Change:

```qml
        Connections {
            target: bridge
            function onCollapseRequested() { expandTimer.stop(); island.expanded = false }
        }
```

to:

```qml
        Connections {
            target: bridge
            function onCollapseRequested() { expandTimer.stop(); island.expanded = false }
            function onSessionFinished(sid, reason, text) {
                finishNoticeTimer.stop()
                leaveTimer.stop()
                expandTimer.stop()
                island.notifySid = sid
                island.notifyReason = reason
                island.notifyText = text
                island.expanded = true
                finishNoticeTimer.restart()
            }
        }
```

- [ ] **Step 3: Add the notification auto-collapse timer**

In `src/island.qml`, immediately after the existing timers:

```qml
        Timer { id: leaveTimer;  interval: 250; onTriggered: island.expanded = false }
        Timer { id: expandTimer; interval: 0;   onTriggered: island.expanded = true  }
```

add:

```qml
        Timer {
            id: finishNoticeTimer
            interval: 2500
            onTriggered: {
                island.notifyText = ""
                if (!hoverHandler.hovered && !islandDragH.active && !cardsList.cardHorzDragging && !emptyStateDragH.active)
                    island.expanded = false
            }
        }
```

- [ ] **Step 4: Add the floating pill overlay**

In `src/island.qml`, inside `Item { id: expandedArea ... }`, add this `Rectangle` immediately after the closing brace of `ListView { id: cardsList ... }` and before the closing brace of `expandedArea`:

```qml
            Rectangle {
                id: finishNotice
                z: 10
                visible: island.notifyVisible && island.expanded
                opacity: visible ? 1.0 : 0.0
                anchors {
                    horizontalCenter: parent.horizontalCenter
                    top: parent.top
                    topMargin: Math.round(6 * island.sf)
                }
                width: Math.min(parent.width - Math.round(24 * island.sf),
                                finishNoticeText.implicitWidth + Math.round(28 * island.sf))
                height: Math.round(28 * island.sf)
                radius: height / 2
                color: island.notifyReason === "completed" ? "#0e2a1c" : "#2a0e0e"
                border.width: 1
                border.color: island.notifyReason === "completed" ? "#2f8f5b" : "#9f3d3d"
                enabled: false

                Behavior on opacity { NumberAnimation { duration: 140 } }

                Text {
                    id: finishNoticeText
                    anchors.centerIn: parent
                    text: island.notifyText
                    color: island.notifyReason === "completed" ? "#9ff0bf" : "#ffb3b3"
                    font {
                        family: "Microsoft YaHei UI"
                        pixelSize: Math.round(11 * island.sf)
                        bold: true
                    }
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
            }
```

This block must be a sibling of `ListView`, not inside a delegate.

- [ ] **Step 5: Run syntax and Python regression checks**

Run:

```powershell
python -m py_compile src\hook.py src\models.py src\ui_qml.py src\win32.py install.py
python test_scenarios.py
```

Expected:

- `py_compile` exits `0`.
- `test_scenarios.py` exits `0`.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add src/island.qml
git commit -m "feat: show finish notification pill"
```

Expected: commit contains only `src/island.qml`.

---

### Task 4: Manual Verification and Cleanup

**Files:**
- Read: `src/hook.py`
- Read: `src/ui_qml.py`
- Read: `src/island.qml`
- Read: `%LOCALAPPDATA%\VibeBar\state.json`

- [ ] **Step 1: Start or restart VibeBar**

If VibeBar is not running, launch it with:

```powershell
wscript.exe vibebar.vbs
```

If it is already running, quit it via the existing right-click double-click gesture, then launch it again.

Expected: the island is visible and behaves like before on hover.

- [ ] **Step 2: Create a visible test session**

Run:

```powershell
$payload = @{session_id='manual-finish-notify'; hook_event_name='SessionStart'; cwd='E:\vibebar'; model='manual-test'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-notify'; hook_event_name='UserPromptSubmit'; cwd='E:\vibebar'; prompt='manual notification test'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Expected: VibeBar shows a running session for `vibebar`.

- [ ] **Step 3: Verify normal completion notification**

Run:

```powershell
$payload = @{session_id='manual-finish-notify'; hook_event_name='Stop'; cwd='E:\vibebar'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Expected:

- The card flashes.
- The island auto-expands.
- A floating pill displays `Task complete`.
- The island auto-collapses after about 2.5 seconds if the mouse is not hovering.

- [ ] **Step 4: Verify interrupted notification**

Run:

```powershell
$payload = @{session_id='manual-finish-notify'; hook_event_name='UserPromptSubmit'; cwd='E:\vibebar'; prompt='manual interruption test'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-notify'; hook_event_name='StopFailure'; cwd='E:\vibebar'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Expected:

- The card flashes.
- The island auto-expands.
- A floating pill displays `Task interrupted`.
- Hovering over the island keeps it open past 2.5 seconds.

- [ ] **Step 5: Remove the manual test session**

Run:

```powershell
$payload = @{session_id='manual-finish-notify'; hook_event_name='SessionEnd'; cwd='E:\vibebar'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Expected: the manual test card disappears.

- [ ] **Step 6: Final repository check**

Run:

```powershell
git status --short
```

Expected:

- No modified implementation files remain unstaged.
- Pre-existing unrelated `install.py` or `.superpowers/` changes may still appear. Leave them untouched unless the user asks to clean them.

---

## Self-Review Checklist

- Spec coverage: Task 1 covers hook `finish_reason`; Task 2 covers new finish detection and bridge signal; Task 3 covers auto-expand, pill display, timer, and interaction-safe collapse; Task 4 covers manual QML behavior.
- Placeholder scan: this plan contains concrete file paths, code snippets, commands, and expected outputs.
- Type consistency: `sessionFinished` uses `(sid: str, reason: str, text: str)` across `models.py`, `ui_qml.py`, and `island.qml`; notification state uses `notifySid`, `notifyReason`, `notifyText`, and `notifyVisible`.
