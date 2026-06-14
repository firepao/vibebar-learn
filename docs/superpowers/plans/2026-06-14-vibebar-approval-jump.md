# VibeBar Approval State and Jump Plan

> REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** When Claude Code or Codex asks the user to confirm a command/tool action, VibeBar should show an explicit attention state and let the user jump back to the window that needs approval.

**Current finding:** The existing `bridge.jump(sid)` only guesses a VS Code window from the cwd basename in the window title. That is not reliable enough and often fails. The new path should prefer a foreground-window snapshot captured when the approval event arrives, with cwd/VS Code matching as fallback.

## Task 1: Capture Approval Metadata

- [x] Add tests for PermissionRequest metadata:
  - `needs_attention=True`
  - `attention_tool`
  - command/summary extracted from `tool_input.command`
  - `attention_at`
- [x] Add tests that `PermissionDenied`, `PostToolUse`, `UserPromptSubmit`, and `Stop` clear approval metadata.
- [x] Add tests for `Notification(permission_prompt)` summary fallback.
- [x] Implement helper functions in `src/hook.py` to extract approval metadata.

## Task 2: Capture and Use Jump Target

- [x] Add `win32.get_foreground_snapshot(exclude_hwnd=0)` returning `hwnd`, `title`, `pid`.
- [x] In `src/ui_qml.py`, record a foreground snapshot for newly observed approval sessions.
- [x] Add `attention_jump_hwnd`, `attention_jump_title`, and `attention_jump_pid` to the session state.
- [x] Update `IslandBridge.jump` to try `attention_jump_hwnd` first, then fall back to VS Code cwd lookup.

## Task 3: Show Approval State in QML

- [x] Add model roles for approval label/detail.
- [x] Render attention cards with a clear "Needs approval" label.
- [x] Show the tool name and command/summary when present.
- [x] Make attention cards jump on single click, while preserving double-click jump for normal cards.

## Task 4: Verify

- [x] Run `python -m py_compile src\hook.py src\models.py src\ui_qml.py src\win32.py install.py`.
- [x] Run `E:\anaconda\envs\vibebar\python.exe test_scenarios.py`.
- [x] Manually inject a `PermissionRequest` event and confirm the card displays approval state.
- [x] Manually verify jump behavior from an approval card.

## Constraints

- Do not touch unrelated local `install.py` changes.
- Do not rely on the visual companion service.
- Do not push to `upstream`.
