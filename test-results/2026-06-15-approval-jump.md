# Approval Jump Test Results

Date: 2026-06-15
Branch: feature/finish-notification
Commit: 4e2a898 feat: show approval prompts with jump target

## Automated Checks

- `python -m py_compile src\hook.py src\models.py src\ui_qml.py src\win32.py install.py`
  - Result: passed
- `E:\anaconda\envs\vibebar\python.exe test_scenarios.py`
  - Result: passed, 166/166

## Manual Verification

Injected a `PermissionRequest` event for session `manual-approval-jump`.

Payload fields used:

- `tool_name`: `Bash`
- `command`: `echo approval-check`

Observed state fields:

- `needs_attention`: `true`
- `attention_tool`: `Bash`
- `attention_detail`: `echo approval-check`
- `attention_at`: present
- `attention_jump_hwnd`, `attention_jump_title`, `attention_jump_pid`: present after UI polling

## Notes

- The attention card shows `Needs approval` with tool and command context.
- Clicking the attention card prefers the captured foreground window.
- If no captured foreground window is available, jump falls back to the existing VS Code cwd matching behavior.
