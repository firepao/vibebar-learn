# Agent Overlay Behavior Update

Date: 2026-06-28
Branch: feature/finish-notification

## Change Under Test

Reworked the agent halo overlay from a foreground-window-attached indicator into a screen-level status indicator.

Expected behavior:

- The main top/bottom VibeBar island behavior is unchanged.
- The halo defaults to the screen bottom-right instead of the active application's bottom-right corner.
- Users can drag the halo; the position is saved in `%LOCALAPPDATA%\VibeBar\ui_config.json` as `agent_overlay_x` and `agent_overlay_y`.
- The halo only appears when a visible Claude/Codex session is active, in background work, or needs attention.
- The halo hides while the foreground page is the active agent page, including captured agent windows, Codex/Claude windows, or the single active terminal-host scenario.
- Clicking the halo jumps back to the captured session window, falling back to the existing VS Code cwd matching path.

## Automated Checks

- `python -m py_compile src\hook.py src\models.py src\ui_qml.py src\win32.py install.py`
  - Result: passed
- `E:\anaconda\envs\vibebar\python.exe test_scenarios.py`
  - Result: passed, 166/166

## Notes

The previous window-attached behavior could place the halo outside the visible area for fullscreen apps. The new behavior uses screen coordinates and clamps saved positions to the current primary screen work area.
