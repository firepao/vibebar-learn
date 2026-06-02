# VibeBar Finish Notification Design

## Goal

When a tracked Claude or Codex task completes or is interrupted, VibeBar should react inside the island itself. The first version will combine the existing card flash with a short automatic island expansion and a concise in-island notification.

## Scope

In scope:

- React to newly observed `finished_at` changes for visible primary sessions.
- Distinguish normal completion from interruption using a session-level finish reason.
- Reuse the existing `finished_at` observer and card flash path in `ui_qml.py`.
- Auto-expand the island briefly, show the completion/interruption message, then auto-collapse only when the user is not hovering or dragging.
- Preserve the existing hover, drag, close, reorder, and VS Code jump behaviors.

Out of scope for this version:

- Windows system notifications or toast popups.
- Persistent notification history.
- A separate event queue in `state.json`.
- Notifications for `SessionEnd` after the session has already been removed.

## User Experience

On a new finish event, the island should:

1. Keep the current card flash behavior.
2. Auto-expand as if the user hovered over it.
3. Show a small status message for the affected session.
4. Auto-collapse after roughly 2.5 seconds if the user is not hovering, dragging the island, or dragging cards.

Message labels:

- `Stop`: "Task complete"
- `StopFailure`: "Task interrupted"
- Stale cleanup that turns a running session idle: "Task interrupted"

The notification should be brief and non-modal. If the user moves the mouse over the island, the normal hover behavior takes over and the island remains open until hover rules collapse it.

## Architecture

### Hook State

`src/hook.py` will add a `finish_reason` field when a task transitions to idle:

- `Stop` sets `finish_reason` to `completed`.
- `StopFailure` sets `finish_reason` to `interrupted`.
- `cleanup_stale_sessions()` sets `finish_reason` to `stale` when it idles an old running session.

`UserPromptSubmit` clears `finished_at` and `finish_reason`, so a new prompt cannot inherit the last task's notification state.

### UI Bridge

`src/models.py` will expose a Qt signal on `IslandBridge`:

```python
sessionFinished = pyqtSignal(str, str, str)
```

Arguments:

- `sid`
- `reason`
- display text

### Finish Detection

`src/ui_qml.py` already tracks `finished_at` in `_last_finished_at` and calls `_flash_done(sid)` when a new finish timestamp appears. That path will be extended to:

1. Ignore initial historical `finished_at` values, as it already does through `last_seen`.
2. Flash the card.
3. Read `finish_reason`, map it to display text, and emit `bridge.sessionFinished(...)`.

### QML Behavior

`src/island.qml` will listen for `bridge.sessionFinished`.

On signal:

- Set notification state fields on the island: `notifySid`, `notifyText`, and `notifyReason`.
- Expand the island immediately.
- Start a notification timer.
- When the timer fires, clear the notification and collapse only if normal user interaction is inactive.

The notification view should be a compact floating pill near the top center of the expanded island. It overlays the cards briefly and does not change row height, card order, or drag geometry.

## Error Handling

- Missing `finish_reason` defaults to `completed`, preserving behavior for old state files.
- Unknown reason values display "Task complete" unless mapped later.
- If the session is no longer visible by the time the signal fires, the flash path already guards by checking model order; QML should also tolerate an unknown `sid`.
- Notification timers should restart on a new finish event so rapid consecutive finishes show the latest event.

## Testing

Automated tests should cover the Python-side state and event mapping:

- `Stop` sets `finish_reason=completed`.
- `StopFailure` sets `finish_reason=interrupted`.
- `UserPromptSubmit` clears `finish_reason`.
- Stale running cleanup sets `finish_reason=stale`.
- Finish event mapping emits the right display text without emitting for the first historical load.

Manual verification should cover QML behavior:

- A running session that receives `Stop` flashes, expands, shows "Task complete", then collapses.
- A running session that receives `StopFailure` shows "Task interrupted".
- Hovering during the notification keeps the island open.
- Dragging the island or cards is not interrupted by the auto-collapse timer.

## Risks

- QML behavior is harder to unit test in this repository, so the bridge signal and state mapping should be kept small and deterministic.
- Too aggressive auto-expansion could feel distracting. The first version should use a short timer and respect hover/drag state.
- Stale cleanup is a heuristic, so labeling it as interrupted is useful but not a definitive process failure.
