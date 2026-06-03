# VibeBar CodeIsland Finish Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade VibeBar's current finish pill into a CodeIsland-inspired finish popup surface that opens when a task completes or is interrupted, holds while hovered, and queues rapid finish events.

**Architecture:** Keep VibeBar's existing hook and `finished_at` detection path. Extend the PyQt bridge signal to send enough session context for a richer QML popup, then replace the current overlay pill with a lightweight QML `finishNotice` surface, queue, and hover-aware collapse lifecycle.

**Tech Stack:** Python 3, PyQt6, Qt Quick/QML, Windows Win32 mask helpers, existing `test_scenarios.py` regression script.

---

## CodeIsland Reference

Useful ideas from `E:\code_island\CodeIsland`:

- `Sources/CodeIsland/IslandSurface.swift`: explicit surface states such as `collapsed`, `sessionList`, and `completionCard`.
- `Sources/CodeIsland/AppState.swift`: `completionQueue`, `completionHasBeenEntered`, `deferCollapseOnMouseLeave`, and `doShowCompletion`.
- `Sources/CodeIsland/NotchPanelView.swift`: completion card hover behavior that defers collapse until the mouse leaves.

Do not port macOS-specific pieces:

- `NSPanel`, `NSScreen`, notch detection, `NSHapticFeedbackManager`, `NSSound`, AppleScript, and Accessibility-based terminal activation.

---

## File Structure

- Modify `src/models.py`: change `IslandBridge.sessionFinished` from three strings to six strings.
- Modify `src/ui_qml.py`: add a rich finish notice payload helper and emit the extended signal.
- Modify `src/island.qml`: add `surface`, finish notice queue state, hover-aware timers, a dedicated finish popup surface, and target-height mask handling.
- Modify `test_scenarios.py`: add Python-side tests for the richer finish notice helper.

Known dirty state before this plan:

- `install.py` has unrelated local changes. Do not stage or commit it for this feature.

---

### Task 1: Extend Finish Notification Payload

**Files:**
- Modify: `test_scenarios.py`
- Modify: `src/models.py`
- Modify: `src/ui_qml.py`

- [ ] **Step 1: Add failing tests for the rich payload helper**

In `test_scenarios.py`, find section `16. Finish notification payload`. After the existing `_finish_event_payload` checks and before the `else:` block, add:

```python
    notice_fn = getattr(ui_qml, "_finish_notice_payload", None)
    check("_finish_notice_payload exists", callable(notice_fn))

    if callable(notice_fn):
        sess = {
            "finish_reason": "completed",
            "cwd_name": "vibe-bar",
            "cwd": "E:/vibebar/vibe-bar",
            "last_prompt": "implement finish popup",
            "source": "claude",
        }
        should_emit, reason, title, cwd_name, prompt, source = notice_fn(
            True, "", "2026-06-02T10:00:00", sess
        )
        check("finish notice payload emits for seen completed session",
              should_emit is True and reason == "completed" and title == "Task complete",
              (should_emit, reason, title))
        check("finish notice payload includes cwd_name",
              cwd_name == "vibe-bar", cwd_name)
        check("finish notice payload includes prompt",
              prompt == "implement finish popup", prompt)
        check("finish notice payload includes source",
              source == "claude", source)

        sess = {
            "finish_reason": "interrupted",
            "cwd": "E:/vibebar/fallback-name",
            "last_prompt": "",
            "source": "codex",
        }
        should_emit, reason, title, cwd_name, prompt, source = notice_fn(
            True, "2026-06-02T09:59:00", "2026-06-02T10:00:00", sess
        )
        check("finish notice payload maps interrupted",
              should_emit is True and reason == "interrupted" and title == "Task interrupted",
              (should_emit, reason, title))
        check("finish notice payload falls back to cwd basename",
              cwd_name == "fallback-name", cwd_name)
        check("finish notice payload preserves codex source",
              source == "codex", source)
```

Still inside the existing `else:` block for missing `_finish_event_payload`, add these two failure checks:

```python
    check("_finish_notice_payload exists", False, "_finish_event_payload missing")
    check("finish notice payload includes context", False, "_finish_event_payload missing")
```

- [ ] **Step 2: Run tests and confirm the new helper is missing**

Run:

```powershell
E:\anaconda\envs\vibebar\python.exe test_scenarios.py
```

Expected: nonzero exit. The failure should include `_finish_notice_payload exists`.

- [ ] **Step 3: Extend the bridge signal**

In `src/models.py`, change:

```python
class IslandBridge(QObject):
    collapseRequested = pyqtSignal()
    sessionFinished = pyqtSignal(str, str, str)
```

to:

```python
class IslandBridge(QObject):
    collapseRequested = pyqtSignal()
    sessionFinished = pyqtSignal(str, str, str, str, str, str)
```

Signal arguments are:

```text
sid, reason, title, cwd_name, prompt, source
```

- [ ] **Step 4: Add the rich payload helper**

In `src/ui_qml.py`, add this helper immediately after `_finish_event_payload(...)`:

```python
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
```

- [ ] **Step 5: Emit the extended signal from `_apply_state`**

In `src/ui_qml.py`, replace this block:

```python
            should_notify, reason, text = _finish_event_payload(
                has_seen, last_seen, finished_at, sess.get("finish_reason")
            )
            if finished_at != last_seen:
                self._last_finished_at[sid] = finished_at
                if should_notify:
                    self._flash_done(sid)
                    self.bridge.sessionFinished.emit(sid, reason, text)
```

with:

```python
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
```

- [ ] **Step 6: Run Python regression tests**

Run:

```powershell
E:\anaconda\envs\vibebar\python.exe test_scenarios.py
```

Expected: exit code `0`. The result summary should report all checks passed.

- [ ] **Step 7: Commit Task 1**

Run:

```powershell
git add test_scenarios.py src\models.py src\ui_qml.py
git commit -m "feat: enrich finish notification payload"
```

Expected: commit contains only `test_scenarios.py`, `src/models.py`, and `src/ui_qml.py`.

---

### Task 2: Add QML Finish Surface State and Queue

**Files:**
- Modify: `src/island.qml`

- [ ] **Step 1: Replace the finish notification properties**

In `src/island.qml`, inside `Rectangle { id: island ... }`, replace the current notification properties:

```qml
        property string notifySid: ""
        property string notifyText: ""
        property string notifyReason: "completed"
        property bool notifyIsError: notifyReason === "interrupted" || notifyReason === "stale"
        property bool notifyVisible: notifyText.length > 0
```

with:

```qml
        property string surface: "sessions"
        property bool finishSurfaceActive: surface === "finishNotice"
        property int finishH: Math.round(104 * sf)
        property int targetH: finishSurfaceActive ? finishH : expandedH

        property string notifySid: ""
        property string notifyTitle: ""
        property string notifyCwdName: ""
        property string notifyPrompt: ""
        property string notifyReason: "completed"
        property string notifySource: "claude"
        property var notifyQueue: []
        property bool notifyEntered: false
        property bool notifyCollapseDeferred: false
        property bool notifyIsError: notifyReason === "interrupted" || notifyReason === "stale"
        property bool notifyVisible: notifyTitle.length > 0
```

- [ ] **Step 2: Add finish surface helper functions**

Still inside `Rectangle { id: island ... }`, after `Component.onCompleted: displayCount = sessionsModel.sessionCount`, add:

```qml
        function hasActiveInteraction() {
            return hoverHandler.hovered
                || islandDragH.active
                || cardsList.cardHorzDragging
                || emptyStateDragH.active
        }

        function enqueueFinishNotice(sid, reason, title, cwdName, prompt, source) {
            var notice = {
                sid: sid,
                reason: reason,
                title: title,
                cwdName: cwdName,
                prompt: prompt,
                source: source
            }
            if (finishSurfaceActive && notifyVisible) {
                var q = notifyQueue.slice()
                q.push(notice)
                notifyQueue = q
                return
            }
            showFinishNotice(notice)
        }

        function showFinishNotice(notice) {
            finishNoticeTimer.stop()
            finishLeaveTimer.stop()
            leaveTimer.stop()
            expandTimer.stop()
            notifySid = notice.sid
            notifyReason = notice.reason
            notifyTitle = notice.title
            notifyCwdName = notice.cwdName
            notifyPrompt = notice.prompt
            notifySource = notice.source
            notifyEntered = false
            notifyCollapseDeferred = false
            surface = "finishNotice"
            if (!islandDragH.active)
                expanded = true
            finishNoticeTimer.restart()
        }

        function clearFinishNotice() {
            notifySid = ""
            notifyTitle = ""
            notifyCwdName = ""
            notifyPrompt = ""
            notifyReason = "completed"
            notifySource = "claude"
            notifyEntered = false
            notifyCollapseDeferred = false
            surface = "sessions"
        }

        function showNextFinishNoticeOrCollapse() {
            if (notifyEntered && hoverHandler.hovered) {
                notifyCollapseDeferred = true
                return
            }
            if (notifyQueue.length > 0) {
                var q = notifyQueue.slice()
                var next = q.shift()
                notifyQueue = q
                showFinishNotice(next)
                return
            }
            clearFinishNotice()
            if (!hasActiveInteraction())
                expanded = false
        }

        function dismissFinishNoticeAfterLeave() {
            finishNoticeTimer.stop()
            notifyEntered = false
            notifyCollapseDeferred = false
            if (notifyQueue.length > 0) {
                var q = notifyQueue.slice()
                var next = q.shift()
                notifyQueue = q
                showFinishNotice(next)
                return
            }
            clearFinishNotice()
            if (!islandDragH.active && !cardsList.cardHorzDragging && !emptyStateDragH.active)
                expanded = false
        }
```

- [ ] **Step 3: Update the bridge handler**

Replace the current handler:

```qml
            function onSessionFinished(sid, reason, text) {
                finishNoticeTimer.stop()
                leaveTimer.stop()
                expandTimer.stop()
                island.notifySid = sid
                island.notifyReason = reason
                island.notifyText = text
                if (!islandDragH.active)
                    island.expanded = true
                finishNoticeTimer.restart()
            }
```

with:

```qml
            function onSessionFinished(sid, reason, title, cwdName, prompt, source) {
                island.enqueueFinishNotice(sid, reason, title, cwdName, prompt, source)
            }
```

- [ ] **Step 4: Make island height surface-aware**

Replace:

```qml
        height: expanded ? expandedH : collapsedH
```

with:

```qml
        height: expanded ? targetH : collapsedH
```

In `onExpandedChanged`, replace:

```qml
                _maskH = expandedH
                bridge.onExpandStart(expandedH)
```

with:

```qml
                _maskH = targetH
                bridge.onExpandStart(targetH)
```

After the existing `onHeightChanged` block, add:

```qml
        onTargetHChanged: {
            if (expanded) {
                _maskH = targetH
                bridge.onExpandStart(targetH)
            }
        }
```

- [ ] **Step 5: Make hover behavior match CodeIsland completion cards**

Replace the existing `HoverHandler` body:

```qml
        HoverHandler {
            id: hoverHandler
            onHoveredChanged: {
                if (hovered) { leaveTimer.stop(); expandTimer.restart() }
                else          { expandTimer.stop(); if (!islandDragH.active && !cardsList.cardHorzDragging && !emptyStateDragH.active) leaveTimer.restart() }
            }
        }
```

with:

```qml
        HoverHandler {
            id: hoverHandler
            onHoveredChanged: {
                if (island.finishSurfaceActive) {
                    if (hovered) {
                        leaveTimer.stop()
                        finishLeaveTimer.stop()
                        expandTimer.stop()
                        island.notifyEntered = true
                    } else {
                        expandTimer.stop()
                        if (!islandDragH.active && !cardsList.cardHorzDragging && !emptyStateDragH.active)
                            finishLeaveTimer.restart()
                    }
                    return
                }
                if (hovered) {
                    leaveTimer.stop()
                    expandTimer.restart()
                } else {
                    expandTimer.stop()
                    if (!islandDragH.active && !cardsList.cardHorzDragging && !emptyStateDragH.active)
                        leaveTimer.restart()
                }
            }
        }
```

- [ ] **Step 6: Replace finish timers**

Replace the existing `finishNoticeTimer`:

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

with:

```qml
        Timer {
            id: finishNoticeTimer
            interval: 4200
            onTriggered: island.showNextFinishNoticeOrCollapse()
        }
        Timer {
            id: finishLeaveTimer
            interval: 120
            onTriggered: island.dismissFinishNoticeAfterLeave()
        }
```

- [ ] **Step 7: Hide the normal session list while the finish surface is active**

In the empty-state `Rectangle`, replace:

```qml
                visible: sessionsModel.sessionCount === 0
```

with:

```qml
                visible: sessionsModel.sessionCount === 0 && !island.finishSurfaceActive
```

In `ListView { id: cardsList ... }`, add this property near the other top-level ListView properties:

```qml
                visible: !island.finishSurfaceActive
```

- [ ] **Step 8: Replace the floating pill with the finish surface card**

Delete the current `Rectangle { id: finishNotice ... }` block inside `Item { id: expandedArea ... }`.

In the same location, add:

```qml
            Item {
                id: finishSurface
                z: 10
                visible: island.finishSurfaceActive && island.expanded
                opacity: visible ? 1.0 : 0.0
                anchors.fill: parent
                enabled: visible

                Behavior on opacity { NumberAnimation { duration: 140 } }

                Rectangle {
                    anchors {
                        fill: parent
                        margins: Math.round(8 * island.sf)
                    }
                    radius: Math.round(14 * island.sf)
                    color: island.notifyIsError ? "#241216" : "#102017"
                    border.width: 1
                    border.color: island.notifyIsError ? "#9f3d3d" : "#2f8f5b"

                    Rectangle {
                        id: finishIcon
                        width: Math.round(34 * island.sf)
                        height: width
                        radius: width / 2
                        anchors {
                            left: parent.left
                            leftMargin: Math.round(12 * island.sf)
                            verticalCenter: parent.verticalCenter
                        }
                        color: island.notifyIsError ? "#5d2525" : "#1d5a39"

                        Text {
                            anchors.centerIn: parent
                            text: island.notifyIsError ? "!" : "OK"
                            color: island.notifyIsError ? "#ffb3b3" : "#9ff0bf"
                            font {
                                family: "Microsoft YaHei UI"
                                pixelSize: Math.round((island.notifyIsError ? 18 : 10) * island.sf)
                                bold: true
                            }
                        }
                    }

                    Text {
                        id: finishTitle
                        anchors {
                            left: finishIcon.right
                            leftMargin: Math.round(12 * island.sf)
                            right: sourceBadge.left
                            rightMargin: Math.round(8 * island.sf)
                            top: parent.top
                            topMargin: Math.round(16 * island.sf)
                        }
                        text: island.notifyTitle
                        color: island.notifyIsError ? "#ffb3b3" : "#9ff0bf"
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        font {
                            family: "Microsoft YaHei UI"
                            pixelSize: Math.round(13 * island.sf)
                            bold: true
                        }
                    }

                    Rectangle {
                        id: sourceBadge
                        anchors {
                            right: parent.right
                            rightMargin: Math.round(12 * island.sf)
                            top: parent.top
                            topMargin: Math.round(15 * island.sf)
                        }
                        width: Math.round(34 * island.sf)
                        height: Math.round(20 * island.sf)
                        radius: Math.round(10 * island.sf)
                        color: island.notifySource === "codex" ? "#1b2748" : "#402719"

                        Text {
                            anchors.centerIn: parent
                            text: island.notifySource === "codex" ? "CX" : "CC"
                            color: island.notifySource === "codex" ? "#9cb8ff" : "#ffb16d"
                            font {
                                family: "Microsoft YaHei UI"
                                pixelSize: Math.round(10 * island.sf)
                                bold: true
                            }
                        }
                    }

                    Text {
                        id: finishCwd
                        anchors {
                            left: finishIcon.right
                            leftMargin: Math.round(12 * island.sf)
                            right: parent.right
                            rightMargin: Math.round(12 * island.sf)
                            top: finishTitle.bottom
                            topMargin: Math.round(7 * island.sf)
                        }
                        text: island.notifyCwdName.length > 0 ? island.notifyCwdName : "Session"
                        color: "#f2f4f8"
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        font {
                            family: "Microsoft YaHei UI"
                            pixelSize: Math.round(12 * island.sf)
                            bold: true
                        }
                    }

                    Text {
                        anchors {
                            left: finishIcon.right
                            leftMargin: Math.round(12 * island.sf)
                            right: parent.right
                            rightMargin: Math.round(12 * island.sf)
                            top: finishCwd.bottom
                            topMargin: Math.round(5 * island.sf)
                        }
                        text: island.notifyPrompt.length > 0 ? island.notifyPrompt : island.notifySid
                        color: "#9aa3b5"
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        font {
                            family: "Microsoft YaHei UI"
                            pixelSize: Math.round(11 * island.sf)
                        }
                    }
                }
            }
```

- [ ] **Step 9: Run syntax and regression checks**

Run:

```powershell
python -m py_compile src\hook.py src\models.py src\ui_qml.py src\win32.py install.py
E:\anaconda\envs\vibebar\python.exe test_scenarios.py
```

Expected:

- `py_compile` exits `0`.
- `test_scenarios.py` exits `0`.

- [ ] **Step 10: Commit Task 2**

Run:

```powershell
git add src\island.qml
git commit -m "feat: show finish popup surface"
```

Expected: commit contains only `src/island.qml`.

---

### Task 3: Manual Verification

**Files:**
- Read: `src/island.qml`
- Read: `%LOCALAPPDATA%\VibeBar\state.json`

- [ ] **Step 1: Stop any running VibeBar instance before testing**

If VibeBar is running, close it from the UI. If it is stuck, find and stop the Python process that is running `src\ui_qml.py`.

Expected: no VibeBar window remains before starting a clean test.

- [ ] **Step 2: Start VibeBar**

Run:

```powershell
wscript.exe vibebar.vbs
```

Expected: the island appears at the top of the screen.

- [ ] **Step 3: Create a manual visible test session**

Run:

```powershell
$payload = @{session_id='manual-finish-popup'; hook_event_name='SessionStart'; cwd='E:\vibebar\vibe-bar'; model='manual-test'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Then run:

```powershell
$payload = @{session_id='manual-finish-popup'; hook_event_name='UserPromptSubmit'; cwd='E:\vibebar\vibe-bar'; prompt='manual popup verification'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Expected: VibeBar shows a running session for `vibe-bar`.

- [ ] **Step 4: Verify normal completion popup**

Run:

```powershell
$payload = @{session_id='manual-finish-popup'; hook_event_name='Stop'; cwd='E:\vibebar\vibe-bar'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Expected:

- The card flashes.
- The island expands to a compact finish popup, not the full session list.
- The popup title is `Task complete`.
- The popup shows `vibe-bar`, `manual popup verification`, and source badge `CC`.
- If the mouse never enters the popup, it closes after about 4.2 seconds.

- [ ] **Step 5: Verify hover defers collapse**

Run:

```powershell
$payload = @{session_id='manual-finish-popup'; hook_event_name='UserPromptSubmit'; cwd='E:\vibebar\vibe-bar'; prompt='hover keeps popup open'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-popup'; hook_event_name='Stop'; cwd='E:\vibebar\vibe-bar'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Before 4.2 seconds pass, move the mouse into the popup and keep it there.

Expected:

- The popup remains open while hovered.
- After the mouse leaves, the popup closes.

- [ ] **Step 6: Verify interrupted popup**

Run:

```powershell
$payload = @{session_id='manual-finish-popup'; hook_event_name='UserPromptSubmit'; cwd='E:\vibebar\vibe-bar'; prompt='interruption popup verification'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-popup'; hook_event_name='StopFailure'; cwd='E:\vibebar\vibe-bar'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Expected:

- The popup title is `Task interrupted`.
- The popup uses the error color path.
- The source badge remains `CC`.

- [ ] **Step 7: Verify queueing with rapid completions**

Run:

```powershell
$payload = @{session_id='manual-finish-popup-a'; hook_event_name='SessionStart'; cwd='E:\vibebar\vibe-bar'; model='manual-test'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-popup-a'; hook_event_name='UserPromptSubmit'; cwd='E:\vibebar\vibe-bar'; prompt='first queued popup'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-popup-b'; hook_event_name='SessionStart'; cwd='E:\vibebar\vibe-bar'; model='manual-test'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-popup-b'; hook_event_name='UserPromptSubmit'; cwd='E:\vibebar\vibe-bar'; prompt='second queued popup'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-popup-a'; hook_event_name='Stop'; cwd='E:\vibebar\vibe-bar'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
$payload = @{session_id='manual-finish-popup-b'; hook_event_name='Stop'; cwd='E:\vibebar\vibe-bar'} | ConvertTo-Json -Compress
$payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
```

Expected:

- The first popup appears.
- The second popup appears after the first popup closes.
- The second event does not overwrite the first while it is visible.

- [ ] **Step 8: Clean up manual sessions**

Run:

```powershell
$ids = @('manual-finish-popup', 'manual-finish-popup-a', 'manual-finish-popup-b')
foreach ($id in $ids) {
  $payload = @{session_id=$id; hook_event_name='SessionEnd'; cwd='E:\vibebar\vibe-bar'} | ConvertTo-Json -Compress
  $payload | E:\anaconda\envs\vibebar\python.exe src\hook.py
}
```

Expected: the manual test cards disappear.

- [ ] **Step 9: Final repository check**

Run:

```powershell
git status --short
```

Expected:

- Feature files are clean after commits.
- Pre-existing unrelated `install.py` changes may still appear and must remain untouched.

---

## Self-Review Checklist

- Spec coverage: The plan keeps the existing finish event source, adds richer popup content, implements a CodeIsland-like finish surface, defers collapse while hovered, and queues rapid finish events.
- Placeholder scan: No steps rely on deferred or unspecified implementation details.
- Type consistency: `sessionFinished` uses six string arguments consistently across `models.py`, `ui_qml.py`, and `island.qml`.
- Scope control: The plan does not port macOS-only CodeIsland features such as `NSPanel`, haptics, sounds, or Accessibility automation.
