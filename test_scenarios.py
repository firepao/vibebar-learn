"""
VibeBar 完整验收测试套件
覆盖 hook.py 所有事件路径 + models.py 颜色逻辑 + _apply_state 过滤/注入

运行: python test_scenarios.py
不需要 PyQt6，不依赖 UI 进程，直接操作 state.json
"""
import json, os, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path

# ── 路径 ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
STATE_PATH = Path(os.environ["LOCALAPPDATA"]) / "VibeBar" / "state.json"

# ── models.py 颜色函数直接 import ───────────────────────────────────────────
from models import (
    _dot_color, _is_background,
    RUNNING_COLOR, BACKGROUND_COLOR, IDLE_COLOR, DOT_EMPTY_COLOR, ATTENTION_COLOR,
    STATUS_RUNNING, STATUS_IDLE,
)

# ── 颜色名映射 ───────────────────────────────────────────────────────────────
COLOR_NAME = {
    RUNNING_COLOR:    "PURPLE",
    BACKGROUND_COLOR: "BLUE",
    IDLE_COLOR:       "GREEN",
    DOT_EMPTY_COLOR:  "GRAY",
    ATTENTION_COLOR:  "RED",
}
def cname(sess): return COLOR_NAME.get(_dot_color(sess), _dot_color(sess))

# ── 测试基础工具 ─────────────────────────────────────────────────────────────
PASS = 0; FAIL = 0

def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  ✓ {label}")
        PASS += 1
    else:
        print(f"  ✗ {label}" + (f" | {detail}" if detail else ""))
        FAIL += 1

def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

def hook(payload, source=None):
    args = ["python", str(ROOT / "src" / "hook.py")]
    env = os.environ.copy()
    if source:
        env["VIBEBAR_SOURCE"] = source
    r = subprocess.run(args, input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return r.stdout.strip()

def load_state():
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except: return {"sessions": {}}

def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)

def get_sess(sid):
    return load_state()["sessions"].get(sid, {})

def cleanup(*sids):
    st = load_state()
    for sid in sids:
        st["sessions"].pop(sid, None)
        st["sessions"].pop(f"codex:{sid}", None)
    st.pop("_pending_rescues", None)
    save_state(st)

def now_iso(): return datetime.now().isoformat(timespec="seconds")
def old_iso(seconds): return (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")

# ════════════════════════════════════════════════════════════════════════════
# 1. 基本生命周期
# ════════════════════════════════════════════════════════════════════════════
section("1. 基本生命周期")

SID = "t-lifecycle"
cleanup(SID)

hook({"session_id": SID, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P", "model": "claude-opus-4-7"})
s = get_sess(SID)
check("SessionStart: status=idle", s.get("status") == "idle")
check("SessionStart: is_primary=True (有 model)", s.get("is_primary") == True)
check("SessionStart: active_subagent_count=0", s.get("active_subagent_count") == 0)
check("SessionStart: active_bash=False", s.get("active_bash") == False)
check("SessionStart: cwd 记录", s.get("cwd") == "C:/dev/P")

hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "do something"})
s = get_sess(SID)
check("UserPromptSubmit: status=running", s.get("status") == "running")
check("UserPromptSubmit: last_prompt 保存", s.get("last_prompt") == "do something")
check("UserPromptSubmit: active_subagent_count 清零", s.get("active_subagent_count") == 0)
check("UserPromptSubmit: needs_attention=False", s.get("needs_attention") == False)
check("UserPromptSubmit: user_closed 清除", "user_closed" not in s)

hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
s = get_sess(SID)
check("Stop: status=idle", s.get("status") == "idle")
check("Stop: active_bash=False", s.get("active_bash") == False)
check("Stop: needs_attention=False", s.get("needs_attention") == False)
check("Stop: finished_at 有值", bool(s.get("finished_at")))

# StopFailure 等同 Stop
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "C:/dev/P", "prompt": "x"})
hook({"session_id": SID, "hook_event_name": "StopFailure", "cwd": "C:/dev/P"})
s = get_sess(SID)
check("StopFailure: status=idle", s.get("status") == "idle")

# SessionStart 无 model 无 resume → is_primary=False
SID2 = "t-noprimary"
cleanup(SID2)
hook({"session_id": SID2, "hook_event_name": "SessionStart", "cwd": "C:/dev/P"})
s = get_sess(SID2)
check("SessionStart(无model无resume): is_primary=False", s.get("is_primary") == False)

# SessionStart source=resume → is_primary=True
SID3 = "t-resume"
cleanup(SID3)
hook({"session_id": SID3, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P", "source": "resume"})
s = get_sess(SID3)
check("SessionStart(source=resume): is_primary=True", s.get("is_primary") == True)

# resume 时不重置 active_subagent_count/active_bash（需同时有 ids 列表）
st = load_state()
st["sessions"][SID3]["active_subagent_ids"] = [{"id": "a1", "ts": now_iso()}, {"id": "a2", "ts": now_iso()}]
st["sessions"][SID3]["active_subagent_count"] = 2
st["sessions"][SID3]["active_bash"] = True
save_state(st)
hook({"session_id": SID3, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P", "source": "resume"})
s = get_sess(SID3)
check("SessionStart(resume): 保留已有 active_subagent_count", s.get("active_subagent_count") == 2)
check("SessionStart(resume): 保留已有 active_bash", s.get("active_bash") == True)

# resume 旧格式迁移：有 count 但无 ids → 保守清零
st = load_state()
st["sessions"][SID3].pop("active_subagent_ids", None)
st["sessions"][SID3]["active_subagent_count"] = 3
save_state(st)
hook({"session_id": SID3, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P", "source": "resume"})
s = get_sess(SID3)
check("SessionStart(resume旧格式): count 清零迁移", s.get("active_subagent_count") == 0)

cleanup(SID, SID2, SID3)

# ════════════════════════════════════════════════════════════════════════════
# 2. 颜色逻辑 (_dot_color)
# ════════════════════════════════════════════════════════════════════════════
section("2. 颜色逻辑 (_dot_color)")

check("PURPLE: status=running",
      cname({"status": "running", "last_prompt": "x"}) == "PURPLE")
check("BLUE: idle + active_subagent_count=1",
      cname({"status": "idle", "active_subagent_count": 1, "last_prompt": "x"}) == "BLUE")
# active_bash=True + idle 在正常 hook 流中不可达（Stop 同时清两者），此处仅验证函数分支存在
check("BLUE(函数分支): idle + active_bash=True（不可达状态，仅测颜色函数）",
      cname({"status": "idle", "active_bash": True, "last_prompt": "x"}) == "BLUE")
check("GREEN: idle + last_prompt 有值",
      cname({"status": "idle", "last_prompt": "x"}) == "GREEN")
check("GRAY: idle + 无 last_prompt",
      cname({"status": "idle"}) == "GRAY")
check("RED: needs_attention=True 覆盖 idle",
      cname({"status": "idle", "needs_attention": True}) == "RED")
check("RED: needs_attention=True 覆盖 running",
      cname({"status": "running", "needs_attention": True}) == "RED")
check("RED: needs_attention=True 覆盖 BLUE",
      cname({"status": "idle", "active_subagent_count": 1, "needs_attention": True}) == "RED")

# ════════════════════════════════════════════════════════════════════════════
# 3. Bash 追踪
# ════════════════════════════════════════════════════════════════════════════
section("3. Bash 追踪")

SID = "t-bash"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "C:/dev/P", "prompt": "x"})
hook({"session_id": SID, "hook_event_name": "PreToolUse", "cwd": "C:/dev/P", "tool_name": "Bash"})
s = get_sess(SID)
check("PreToolUse/Bash(running): active_bash=True", s.get("active_bash") == True)
check("PreToolUse/Bash(running): status 仍=running", s.get("status") == "running")

# 幂等：已 active_bash 再次 PreToolUse 不重复写
hook({"session_id": SID, "hook_event_name": "PreToolUse", "cwd": "C:/dev/P", "tool_name": "Bash"})
s2 = get_sess(SID)
check("PreToolUse/Bash 幂等：重复不改变", s2.get("active_bash") == True)

hook({"session_id": SID, "hook_event_name": "PostToolUse", "cwd": "C:/dev/P", "tool_name": "Bash"})
s = get_sess(SID)
check("PostToolUse/Bash: active_bash=False", s.get("active_bash") == False)
check("PostToolUse/Bash: needs_attention=False", s.get("needs_attention") == False)

# PreToolUse/Bash 在 idle 时 → status 升为 running
hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
hook({"session_id": SID, "hook_event_name": "PreToolUse", "cwd": "C:/dev/P", "tool_name": "Bash"})
s = get_sess(SID)
check("PreToolUse/Bash(idle→running): status=running", s.get("status") == "running")
check("PreToolUse/Bash(idle→running): active_bash=True", s.get("active_bash") == True)

# PostToolUseFailure/Bash 清 active_bash
hook({"session_id": SID, "hook_event_name": "PostToolUseFailure",
      "cwd": "C:/dev/P", "tool_name": "Bash"})
s = get_sess(SID)
check("PostToolUseFailure/Bash: active_bash=False", s.get("active_bash") == False)

# Stop 清 active_bash
hook({"session_id": SID, "hook_event_name": "PreToolUse", "cwd": "C:/dev/P", "tool_name": "Bash"})
hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
s = get_sess(SID)
check("Stop: active_bash=False", s.get("active_bash") == False)

# 非 Bash 工具 → PreToolUse 不影响 active_bash/status
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "C:/dev/P", "prompt": "x"})
hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
hook({"session_id": SID, "hook_event_name": "PreToolUse", "cwd": "C:/dev/P", "tool_name": "Read"})
s = get_sess(SID)
check("PreToolUse/非Bash: 不影响 active_bash", s.get("active_bash") == False)
check("PreToolUse/非Bash: 不影响 status", s.get("status") == "idle")

cleanup(SID)

# ════════════════════════════════════════════════════════════════════════════
# 4. 子代理污染防护（本次修复核心）
# ════════════════════════════════════════════════════════════════════════════
section("4. 子代理污染防护（agent_id guard）")

SID = "t-guard"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "C:/dev/P", "prompt": "x"})
hook({"session_id": SID, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/P", "agent_type": "codex"})
hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
s = get_sess(SID)
check("Stop 后: status=idle, count=1 → BLUE", cname(s) == "BLUE")

# 子代理 PreToolUse（有 agent_id）不污染父 session
hook({"session_id": SID, "hook_event_name": "PreToolUse",
      "cwd": "C:/dev/P", "tool_name": "Bash",
      "agent_id": "sub-abc", "agent_type": "claude"})
s = get_sess(SID)
check("子代理 PreToolUse: status 仍=idle", s.get("status") == "idle", s.get("status"))
check("子代理 PreToolUse: active_bash 仍=False", s.get("active_bash") == False)
check("子代理 PreToolUse: 卡片仍=BLUE", cname(s) == "BLUE")

# 父 session 新一轮 Bash 运行中，子代理 PostToolUse 不清 active_bash
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "x2"})
hook({"session_id": SID, "hook_event_name": "PreToolUse",
      "cwd": "C:/dev/P", "tool_name": "Bash"})
s = get_sess(SID)
check("父 Bash 运行中: active_bash=True", s.get("active_bash") == True)
hook({"session_id": SID, "hook_event_name": "PostToolUse",
      "cwd": "C:/dev/P", "tool_name": "Bash",
      "agent_id": "sub-abc", "agent_type": "claude"})
s = get_sess(SID)
check("子代理 PostToolUse: 父 active_bash 仍=True", s.get("active_bash") == True, s.get("active_bash"))

# 子代理 PostToolUseFailure 不清 active_bash
hook({"session_id": SID, "hook_event_name": "PostToolUseFailure",
      "cwd": "C:/dev/P", "tool_name": "Bash",
      "agent_id": "sub-abc"})
s = get_sess(SID)
check("子代理 PostToolUseFailure: 父 active_bash 仍=True", s.get("active_bash") == True)

# 子代理 PostToolUse 不清 needs_attention
st = load_state(); st["sessions"][SID]["needs_attention"] = True; save_state(st)
hook({"session_id": SID, "hook_event_name": "PostToolUse",
      "cwd": "C:/dev/P", "tool_name": "Read",
      "agent_id": "sub-abc"})
s = get_sess(SID)
check("子代理 PostToolUse: 父 needs_attention 不被清除", s.get("needs_attention") == True)

cleanup(SID)

# ════════════════════════════════════════════════════════════════════════════
# 5. needs_attention（权限提醒）
# ════════════════════════════════════════════════════════════════════════════
section("5. needs_attention（权限提醒）")

SID = "t-attn"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})

hook({"session_id": SID, "hook_event_name": "PermissionRequest", "cwd": "C:/dev/P"})
check("PermissionRequest: needs_attention=True", get_sess(SID).get("needs_attention") == True)

hook({"session_id": SID, "hook_event_name": "PermissionDenied", "cwd": "C:/dev/P"})
check("PermissionDenied: needs_attention=False", get_sess(SID).get("needs_attention") == False)

hook({"session_id": SID, "hook_event_name": "PermissionRequest", "cwd": "C:/dev/P"})
hook({"session_id": SID, "hook_event_name": "PostToolUse",
      "cwd": "C:/dev/P", "tool_name": "Read"})
check("PostToolUse(无agent_id): needs_attention=False", get_sess(SID).get("needs_attention") == False)

# Notification permission_prompt 类型
hook({"session_id": SID, "hook_event_name": "Notification",
      "cwd": "C:/dev/P", "notification_type": "permission_prompt"})
check("Notification(permission_prompt): needs_attention=True",
      get_sess(SID).get("needs_attention") == True)

hook({"session_id": SID, "hook_event_name": "Notification",
      "cwd": "C:/dev/P", "notification_type": "other_type"})
check("Notification(其他类型): needs_attention 不变（仍True）",
      get_sess(SID).get("needs_attention") == True)

hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
check("Stop: needs_attention=False", get_sess(SID).get("needs_attention") == False)

hook({"session_id": SID, "hook_event_name": "PermissionRequest", "cwd": "C:/dev/P"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "x"})
check("UserPromptSubmit: needs_attention=False", get_sess(SID).get("needs_attention") == False)

cleanup(SID)

# ════════════════════════════════════════════════════════════════════════════
# 6. SubagentStart/Stop 计数
# ════════════════════════════════════════════════════════════════════════════
section("6. SubagentStart/Stop 计数")

SID = "t-count"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "C:/dev/P", "prompt": "x"})

hook({"session_id": SID, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/P", "agent_type": "general"})
check("SubagentStart: count=1", get_sess(SID).get("active_subagent_count") == 1)

hook({"session_id": SID, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/P", "agent_type": "general"})
check("SubagentStart×2: count=2", get_sess(SID).get("active_subagent_count") == 2)

hook({"session_id": SID, "hook_event_name": "SubagentStop", "cwd": "C:/dev/P"})
check("SubagentStop: count=1", get_sess(SID).get("active_subagent_count") == 1)

hook({"session_id": SID, "hook_event_name": "SubagentStop", "cwd": "C:/dev/P"})
check("SubagentStop: count=0", get_sess(SID).get("active_subagent_count") == 0)

hook({"session_id": SID, "hook_event_name": "SubagentStop", "cwd": "C:/dev/P"})
check("SubagentStop 不降到负数: count=0", get_sess(SID).get("active_subagent_count") == 0)

# 超 TTL 的孤儿条目（SubagentStop 未触发）在 UPS 时被清理
st = load_state()
st["sessions"][SID]["active_subagent_ids"] = [{"id": "", "ts": old_iso(400)}]
st["sessions"][SID]["active_subagent_count"] = 1
save_state(st)
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "new turn"})
check("超TTL孤儿在 UPS 时被清理: count=0",
      get_sess(SID).get("active_subagent_count") == 0)

# 未超 TTL 的后台 agent 在 UPS 时被保留
hook({"session_id": SID, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/P", "agent_type": "general", "agent_id": "live-agent-1"})
check("SubagentStart(live): count=1", get_sess(SID).get("active_subagent_count") == 1)
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "new turn while agent runs"})
check("UPS 保留未超TTL的后台 agent: count=1",
      get_sess(SID).get("active_subagent_count") == 1)

# Codex 的 SubagentStart/SubagentStop 被忽略
env_codex = os.environ.copy(); env_codex["VIBEBAR_SOURCE"] = "codex"
cx_sid = f"codex:{SID}"
# reset count on parent first
hook({"session_id": SID, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/P", "agent_type": "general"})
count_before = get_sess(SID).get("active_subagent_count")
subprocess.run(["python", str(ROOT/"src"/"hook.py")],
               input=json.dumps({"session_id": SID, "hook_event_name": "SubagentStart",
                                  "cwd": "C:/dev/P", "agent_type": "general"}),
               capture_output=True, text=True, env=env_codex)
check("Codex SubagentStart 不影响父 count",
      get_sess(SID).get("active_subagent_count") == count_before)

cleanup(SID)

# ════════════════════════════════════════════════════════════════════════════
# 7. Codex Rescue 检测
# ════════════════════════════════════════════════════════════════════════════
section("7. Codex Rescue 检测")

PARENT = "t-rescue-parent"
CX = "cx-rescue-child"
cleanup(PARENT, CX)

# 父 session SessionStart
hook({"session_id": PARENT, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/Proj", "model": "m"})
hook({"session_id": PARENT, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/Proj", "prompt": "review"})

# SubagentStart 含 codex → 添加 pending rescue
hook({"session_id": PARENT, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/Proj", "agent_type": "codex-rescue"})
st = load_state()
pending = st.get("_pending_rescues", [])
check("SubagentStart(codex type): _pending_rescues 有条目", len(pending) > 0)
check("_pending_rescues.parent_sid 正确", any(p.get("parent_sid") == PARENT for p in pending))

# Codex SessionStart → 匹配 pending rescue → is_rescue_agent=True
hook({"session_id": CX, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/Proj", "model": "m"}, source="codex")
cx_sess = get_sess(f"codex:{CX}")
check("Codex SessionStart 匹配 rescue: is_rescue_agent=True", cx_sess.get("is_rescue_agent") == True)
check("Codex SessionStart 匹配 rescue: is_primary=False", cx_sess.get("is_primary") == False)
check("Codex SessionStart 匹配 rescue: parent_sid 正确", cx_sess.get("parent_sid") == PARENT)
st = load_state()
check("匹配后 _pending_rescues 条目被移除", len(st.get("_pending_rescues", [])) == 0)

# Codex UserPromptSubmit 含 --wait → is_rescue_agent=True 保持
hook({"session_id": CX, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/Proj", "prompt": "--wait Review PR #42"}, source="codex")
cx_sess = get_sess(f"codex:{CX}")
check("Codex UPS(--wait): is_rescue_agent=True", cx_sess.get("is_rescue_agent") == True)
check("Codex UPS(--wait): is_primary=False", cx_sess.get("is_primary") == False)

# Codex UPS 含 <task> 前缀
CX2 = "cx-task"
cleanup(CX2)
hook({"session_id": CX2, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/Proj2", "model": "m"}, source="codex")
hook({"session_id": CX2, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/Proj2", "prompt": "<task>do something</task>"}, source="codex")
cx_sess = get_sess(f"codex:{CX2}")
check("Codex UPS(<task>): is_rescue_agent=True", cx_sess.get("is_rescue_agent") == True)

# Codex SessionStart 无 pending rescue → is_primary=True
CX3 = "cx-nopending"
cleanup(CX3)
hook({"session_id": CX3, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/NoPending", "model": "m"}, source="codex")
cx_sess = get_sess(f"codex:{CX3}")
check("Codex SessionStart(无 pending): is_primary=True", cx_sess.get("is_primary") == True)
check("Codex SessionStart(无 pending): is_rescue_agent 未设置", not cx_sess.get("is_rescue_agent"))

# 第二个 Codex 同 cwd → is_primary=False
CX4 = "cx-second"
cleanup(CX4)
hook({"session_id": CX4, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/NoPending", "model": "m"}, source="codex")
cx_sess4 = get_sess(f"codex:{CX4}")
check("第二个 Codex 同 cwd: is_primary=False", cx_sess4.get("is_primary") == False)

# 普通 Codex UPS（非 rescue）→ is_primary 升为 True
CX5 = "cx-upgrade"
cleanup(CX5)
hook({"session_id": CX5, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/Other", "model": "m"}, source="codex")
hook({"session_id": CX5, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/Other", "prompt": "normal codex prompt"}, source="codex")
cx_sess5 = get_sess(f"codex:{CX5}")
check("普通 Codex UPS: is_primary=True 升级", cx_sess5.get("is_primary") == True)

# Stop 输出 {"continue": true}
out = hook({"session_id": CX, "hook_event_name": "Stop",
             "cwd": "C:/dev/Proj"}, source="codex")
check('Codex Stop 输出 {"continue": true}', '"continue"' in out and "true" in out)

cleanup(PARENT, CX, CX2, CX3, CX4, CX5)

# ════════════════════════════════════════════════════════════════════════════
# 8. _apply_state 过滤逻辑
# ════════════════════════════════════════════════════════════════════════════
section("8. _apply_state 过滤逻辑（纯 Python，不启动 Qt）")

def apply_state_filter(all_sessions):
    """复刻 _apply_state 的 candidates 过滤逻辑"""
    from datetime import datetime, timedelta
    FOUR_HOURS = 4 * 3600
    now_dt = datetime.now()

    def age_sec(s):
        try: return (now_dt - datetime.fromisoformat(s["last_update"])).total_seconds()
        except: return float("inf")

    running_codex_parent_sids = set()
    candidates = {}
    for sid, s in all_sessions.items():
        if s.get("source") == "codex" and s.get("status") == "running" and s.get("parent_sid"):
            running_codex_parent_sids.add(s["parent_sid"])
        if (s.get("is_primary") and not s.get("user_closed")
                and (s.get("status") == "running" or age_sec(s) <= FOUR_HOURS)
                and not s.get("is_rescue_agent")
                and not str(s.get("last_prompt") or "").lstrip().startswith(("--wait", "<task>"))):
            candidates[sid] = s

    sessions = {}
    for sid, s in candidates.items():
        if (s.get("source") != "codex"
                and s.get("status") == "idle"
                and s.get("active_subagent_count", 0) == 0
                and not s.get("active_bash")
                and sid in running_codex_parent_sids):
            s = dict(s)
            s["active_subagent_count"] = 1
        sessions[sid] = s
    return sessions

def mk_sess(**kw):
    base = {"status": "idle", "is_primary": True, "last_update": now_iso(),
            "source": "claude", "last_prompt": "x"}
    base.update(kw)
    return base

# is_primary=False → 不显示
r = apply_state_filter({"s1": mk_sess(is_primary=False)})
check("is_primary=False: 不显示", "s1" not in r)

# is_rescue_agent=True → 不显示
r = apply_state_filter({"s1": mk_sess(is_rescue_agent=True)})
check("is_rescue_agent=True: 不显示", "s1" not in r)

# user_closed=True → 不显示
r = apply_state_filter({"s1": mk_sess(user_closed=True)})
check("user_closed=True: 不显示", "s1" not in r)

# last_prompt starts with --wait → 不显示
r = apply_state_filter({"s1": mk_sess(last_prompt="--wait do task")})
check("last_prompt(--wait): 不显示", "s1" not in r)

# last_prompt starts with <task> → 不显示
r = apply_state_filter({"s1": mk_sess(last_prompt="<task>stuff</task>")})
check("last_prompt(<task>): 不显示", "s1" not in r)

# 老旧 idle session (> 4h) → 不显示
r = apply_state_filter({"s1": mk_sess(last_update=old_iso(4*3600+60))})
check("idle 超 4h: 不显示", "s1" not in r)

# running session 无论多老 → 显示
r = apply_state_filter({"s1": mk_sess(status="running", last_update=old_iso(9999))})
check("running 无论多老: 显示", "s1" in r)

# 正常 idle 近期 session → 显示
r = apply_state_filter({"s1": mk_sess()})
check("正常 idle 近期: 显示", "s1" in r)

# ════════════════════════════════════════════════════════════════════════════
# 9. 虚拟背景注入（virtual background injection）
# ════════════════════════════════════════════════════════════════════════════
section("9. 虚拟背景注入（parent_sid 追踪）")

PARENT_SID = "vb-parent"
CODEX_SID = "codex:vb-child"

# 父 idle + count=0 + codex rescue running with parent_sid → 注入 count=1 → BLUE
sessions_in = {
    PARENT_SID: mk_sess(active_subagent_count=0, active_bash=False),
    CODEX_SID: {
        "status": "running", "is_primary": False, "is_rescue_agent": True,
        "source": "codex", "last_update": now_iso(), "last_prompt": "--wait x",
        "parent_sid": PARENT_SID, "cwd": "C:/dev/P"
    },
}
result = apply_state_filter(sessions_in)
parent_out = result.get(PARENT_SID, {})
check("虚拟注入: 父 idle+count=0+codex running → count注入为1",
      parent_out.get("active_subagent_count") == 1)
check("虚拟注入: 颜色 BLUE", cname(parent_out) == "BLUE")

# Codex rescue 不出现在显示列表（is_rescue_agent=True）
check("虚拟注入: rescue Codex 不出现在显示列表", CODEX_SID not in result)

# 父 count 已=1（SubagentStart 真实值）→ 不注入，值保持 1
sessions_in2 = {
    PARENT_SID: mk_sess(active_subagent_count=1, active_bash=False),
    CODEX_SID: {
        "status": "running", "is_primary": False, "is_rescue_agent": True,
        "source": "codex", "last_update": now_iso(), "last_prompt": "--wait x",
        "parent_sid": PARENT_SID, "cwd": "C:/dev/P"
    },
}
result2 = apply_state_filter(sessions_in2)
check("虚拟注入: 父 count=1 → 不注入（保持真实值）",
      result2.get(PARENT_SID, {}).get("active_subagent_count") == 1)

# 父 running → 不注入（status≠idle）
sessions_in3 = {
    PARENT_SID: mk_sess(status="running", active_subagent_count=0),
    CODEX_SID: {
        "status": "running", "is_primary": False, "is_rescue_agent": True,
        "source": "codex", "last_update": now_iso(), "last_prompt": "--wait x",
        "parent_sid": PARENT_SID,
    },
}
result3 = apply_state_filter(sessions_in3)
check("虚拟注入: 父 running → 不注入",
      result3.get(PARENT_SID, {}).get("active_subagent_count") == 0)

# 无 codex running → 不注入 → GREEN
sessions_in4 = {PARENT_SID: mk_sess(active_subagent_count=0)}
result4 = apply_state_filter(sessions_in4)
check("无 codex running: 不注入 → GREEN", cname(result4.get(PARENT_SID, {})) == "GREEN")

# ════════════════════════════════════════════════════════════════════════════
# 10. 陈旧 session 清理
# ════════════════════════════════════════════════════════════════════════════
section("10. 陈旧 session 清理")

SID = "t-stale"
cleanup(SID)

# 非 primary running > 10min → 强制 idle
st = load_state()
st["sessions"][SID] = {
    "status": "running", "is_primary": False, "source": "claude",
    "last_update": old_iso(700), "cwd": "C:/dev/P"
}
save_state(st)
# 触发任意 hook 触发 cleanup_stale_sessions
hook({"session_id": "trigger-cleanup", "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P2", "model": "m"})
s = get_sess(SID)
check("非primary running >10min → idle", s.get("status") == "idle")

# primary running > 4h → 强制 idle
SID2 = "t-stale2"
cleanup(SID2)
st = load_state()
st["sessions"][SID2] = {
    "status": "running", "is_primary": True, "source": "claude",
    "last_update": old_iso(4*3600+60), "cwd": "C:/dev/P"
}
save_state(st)
hook({"session_id": "trigger-cleanup", "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P2", "model": "m"})
s = get_sess(SID2)
check("primary running >4h → idle", s.get("status") == "idle")

# idle > 24h → 删除
SID3 = "t-stale3"
cleanup(SID3)
st = load_state()
st["sessions"][SID3] = {
    "status": "idle", "is_primary": True, "source": "claude",
    "last_update": old_iso(86400+60), "cwd": "C:/dev/P"
}
save_state(st)
hook({"session_id": "trigger-cleanup", "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P2", "model": "m"})
check("idle >24h → 删除", SID3 not in load_state()["sessions"])

cleanup(SID, SID2, SID3, "trigger-cleanup")

# ════════════════════════════════════════════════════════════════════════════
# 11. 端到端蓝→紫回归测试（完整场景）
# ════════════════════════════════════════════════════════════════════════════
section("11. 端到端：蓝→紫回归（本次修复场景）")

PARENT = "e2e-parent"
cleanup(PARENT)
hook({"session_id": PARENT, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/E2E", "model": "m"})
hook({"session_id": PARENT, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/E2E", "prompt": "review code"})
s = get_sess(PARENT); check("E2E-1 UPS: PURPLE", cname(s) == "PURPLE")

hook({"session_id": PARENT, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/E2E", "agent_type": "codex-rescue"})
s = get_sess(PARENT); check("E2E-2 SubagentStart: 仍 PURPLE(running)", cname(s) == "PURPLE")

hook({"session_id": PARENT, "hook_event_name": "Stop", "cwd": "C:/dev/E2E"})
s = get_sess(PARENT); check("E2E-3 Stop: BLUE(idle+count=1)", cname(s) == "BLUE")

# 子代理 PreToolUse (agent_id) — 旧 bug 此处变紫
hook({"session_id": PARENT, "hook_event_name": "PreToolUse",
      "cwd": "C:/dev/E2E", "tool_name": "Bash",
      "agent_id": "subagent-xyz", "agent_type": "claude"})
s = get_sess(PARENT); check("E2E-4 子代理 PreToolUse: 仍 BLUE（不变紫）", cname(s) == "BLUE",
                             f"got {cname(s)}, status={s.get('status')}")

# 子代理 PostToolUse — 不清 active_bash（active_bash 本来就 False，只验证 count 不受影响）
hook({"session_id": PARENT, "hook_event_name": "PostToolUse",
      "cwd": "C:/dev/E2E", "tool_name": "Bash",
      "agent_id": "subagent-xyz"})
s = get_sess(PARENT); check("E2E-5 子代理 PostToolUse: 仍 BLUE", cname(s) == "BLUE")

# SubagentStop → count=0 → GREEN
hook({"session_id": PARENT, "hook_event_name": "SubagentStop",
      "cwd": "C:/dev/E2E"})
s = get_sess(PARENT); check("E2E-6 SubagentStop: GREEN(idle+count=0)", cname(s) == "GREEN")

cleanup(PARENT)

# ════════════════════════════════════════════════════════════════════════════
# 12. 刁钻边缘场景
# ════════════════════════════════════════════════════════════════════════════
section("12. 刁钻边缘场景")

# unknown session_id + 非关键事件 → 静默跳过（不创建 session）
st_before = load_state()
hook({"session_id": "unknown", "hook_event_name": "PreToolUse",
      "cwd": "C:/dev/P", "tool_name": "Bash"})
check("unknown sid + PreToolUse: 不创建 session",
      "unknown" not in load_state()["sessions"])

# unknown session_id + SessionStart → 允许创建
hook({"session_id": "unknown", "hook_event_name": "SessionStart", "cwd": "C:/dev/P"})
check("unknown sid + SessionStart: 允许创建",
      "unknown" in load_state()["sessions"])
st2 = load_state(); st2["sessions"].pop("unknown", None); save_state(st2)

# 空 payload → 不 crash
try:
    hook({})
    check("空 payload: 不 crash", True)
except Exception as e:
    check("空 payload: 不 crash", False, str(e))

# prompt 超过 80 字符 → 截断
SID = "t-trunc"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "A" * 100})
s = get_sess(SID)
check("prompt 超 80 字符 → 截断到 80", len(s.get("last_prompt", "")) == 80)

# user_closed 被 UserPromptSubmit 清除
st = load_state(); st["sessions"][SID]["user_closed"] = True; save_state(st)
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "reopen"})
check("UPS 清除 user_closed", "user_closed" not in get_sess(SID))

# Codex session 的 sid 用 codex: 前缀
hook({"session_id": "raw-id", "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P", "model": "m"}, source="codex")
check("Codex sid 前缀为 codex:", "codex:raw-id" in load_state()["sessions"])
st2 = load_state(); st2["sessions"].pop("codex:raw-id", None); save_state(st2)

# Stop 不更新 cwd（防子代理 cwd 漂移）
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/Original", "model": "m"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/Original", "prompt": "x"})
hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/Subdir"})
s = get_sess(SID)
check("Stop 不更新 cwd（防漂移）", s.get("cwd") == "C:/dev/Original")

cleanup(SID)

# ════════════════════════════════════════════════════════════════════════════
# 13. Codex 审查补充场景
# ════════════════════════════════════════════════════════════════════════════
section("13. Codex 审查补充场景")

LOCK_PATH = STATE_PATH.with_suffix(".lock")

# --- 13-1: workspace.current_dir 兜底 cwd ---
SID = "t-ws-cwd"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart",
      "workspace": {"current_dir": "C:/dev/WS"}, "model": "m"})
s = get_sess(SID)
check("workspace.current_dir 兜底: cwd 正确写入", s.get("cwd") == "C:/dev/WS")
check("workspace.current_dir 兜底: cwd_name 正确", s.get("cwd_name") == "WS")
cleanup(SID)

# --- 13-2: CLI --source=codex 参数路径 ---
SID = "t-cli-src"
cleanup(SID)
subprocess.run(
    ["python", str(ROOT / "src" / "hook.py"), "--source=codex"],
    input=json.dumps({"session_id": SID, "hook_event_name": "SessionStart",
                      "cwd": "C:/dev/P", "model": "m"}),
    capture_output=True, text=True)
check("CLI --source=codex: session 用 codex: 前缀",
      f"codex:{SID}" in load_state()["sessions"])
cleanup(SID)

# --- 13-3: 锁被占用时 Codex Stop 仍输出 {"continue": true} ---
try:
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    env_cx = os.environ.copy(); env_cx["VIBEBAR_SOURCE"] = "codex"
    r = subprocess.run(
        ["python", str(ROOT / "src" / "hook.py")],
        input=json.dumps({"session_id": "lock-test", "hook_event_name": "Stop",
                          "cwd": "C:/dev/P"}),
        capture_output=True, text=True, env=env_cx)
    check("锁占用时 Codex Stop 输出 continue",
          '"continue"' in r.stdout and "true" in r.stdout)
finally:
    try: os.close(fd)
    except: pass
    LOCK_PATH.unlink(missing_ok=True)

# --- 13-4: _pending_rescues TTL 清理 ---
SID = "t-ttl"
cleanup(SID)
st = load_state()
st.setdefault("_pending_rescues", []).append(
    {"ts": old_iso(61), "cwd": "C:/dev/P", "parent_sid": SID})
save_state(st)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P2", "model": "m"})
st2 = load_state()
expired = [p for p in st2.get("_pending_rescues", []) if p.get("cwd") == "C:/dev/P"]
check("_pending_rescues TTL: 超60s条目被清除", len(expired) == 0)
cleanup(SID)

# --- 13-5: 同 cwd 多个 pending rescue 选最新 ---
PARENT = "t-multi-pending-parent"
CX_OLD = "cx-old"; CX_NEW = "cx-new"
cleanup(PARENT, CX_OLD, CX_NEW)
hook({"session_id": PARENT, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/Multi", "model": "m"})
# 手工插入两条 pending（旧+新，相同 cwd，不同 parent_sid）
st = load_state()
st.setdefault("_pending_rescues", []).extend([
    {"ts": old_iso(5), "cwd": "C:/dev/Multi", "parent_sid": "old-parent"},
    {"ts": now_iso(),  "cwd": "C:/dev/Multi", "parent_sid": PARENT},
])
save_state(st)
hook({"session_id": CX_NEW, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/Multi", "model": "m"}, source="codex")
cx = get_sess(f"codex:{CX_NEW}")
check("多条 pending 选最新: parent_sid 匹配最新条目", cx.get("parent_sid") == PARENT)
cleanup(PARENT, CX_OLD, CX_NEW)

# --- 13-6: rescue agent 收到普通 prompt 不升级为 primary ---
CX = "cx-rescue-noupgrade"
cleanup(CX)
hook({"session_id": CX, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P", "model": "m"}, source="codex")
st = load_state(); st["sessions"][f"codex:{CX}"]["is_rescue_agent"] = True
st["sessions"][f"codex:{CX}"]["is_primary"] = False; save_state(st)
hook({"session_id": CX, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "some normal prompt"}, source="codex")
cx = get_sess(f"codex:{CX}")
check("rescue UPS(普通 prompt): is_rescue_agent 保持 True",
      cx.get("is_rescue_agent") == True)
check("rescue UPS(普通 prompt): is_primary 保持 False",
      cx.get("is_primary") == False)
cleanup(CX)

# --- 13-7: Notification 兼容字段（type/subtype） ---
SID = "t-notif"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
hook({"session_id": SID, "hook_event_name": "Notification",
      "cwd": "C:/dev/P", "type": "permission_prompt"})
check("Notification(type=permission_prompt): needs_attention=True",
      get_sess(SID).get("needs_attention") == True)
hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
hook({"session_id": SID, "hook_event_name": "Notification",
      "cwd": "C:/dev/P", "subtype": "permission_prompt"})
check("Notification(subtype=permission_prompt): needs_attention=True",
      get_sess(SID).get("needs_attention") == True)
cleanup(SID)

# --- 13-8: PermissionDenied 也清 active_bash (Bash tool) ---
SID = "t-permdenied-bash"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "C:/dev/P", "prompt": "x"})
hook({"session_id": SID, "hook_event_name": "PreToolUse", "cwd": "C:/dev/P", "tool_name": "Bash"})
check("setup: active_bash=True", get_sess(SID).get("active_bash") == True)
hook({"session_id": SID, "hook_event_name": "PermissionDenied",
      "cwd": "C:/dev/P", "tool_name": "Bash"})
s = get_sess(SID)
check("PermissionDenied/Bash: active_bash=False", s.get("active_bash") == False)
check("PermissionDenied/Bash: needs_attention=False", s.get("needs_attention") == False)
cleanup(SID)

# --- 13-9: Codex SubagentStop 被忽略 ---
SID = "t-cx-substop"
cleanup(SID)
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "C:/dev/P", "prompt": "x"})
hook({"session_id": SID, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/P", "agent_type": "general"})
count_before = get_sess(SID).get("active_subagent_count")
env_cx = os.environ.copy(); env_cx["VIBEBAR_SOURCE"] = "codex"
subprocess.run(["python", str(ROOT / "src" / "hook.py")],
               input=json.dumps({"session_id": SID, "hook_event_name": "SubagentStop",
                                  "cwd": "C:/dev/P"}),
               capture_output=True, text=True, env=env_cx)
check("Codex SubagentStop 不减父 count",
      get_sess(SID).get("active_subagent_count") == count_before)
cleanup(SID)

# --- 13-10: StopFailure 对 unknown sid 的处理（不触发 handler，但 session 被 setdefault 创建）---
st_before = load_state()
had_unknown = "unknown" in st_before.get("sessions", {})
hook({"session_id": "unknown", "hook_event_name": "StopFailure", "cwd": "C:/dev/P"})
s = get_sess("unknown")
check("StopFailure(unknown): status 不被设为 idle（handler 跳过）",
      s.get("status") != "idle")
st2 = load_state(); st2["sessions"].pop("unknown", None); save_state(st2)

# --- 13-11: _apply_state 注入跳过 active_bash=True 的父 session ---
PARENT_SID = "vb-active-bash"
CODEX_SID2 = "codex:vb-cb2"
sessions_ab = {
    PARENT_SID: mk_sess(active_subagent_count=0, active_bash=True),
    CODEX_SID2: {
        "status": "running", "is_primary": False, "is_rescue_agent": True,
        "source": "codex", "last_update": now_iso(), "last_prompt": "--wait x",
        "parent_sid": PARENT_SID,
    },
}
r_ab = apply_state_filter(sessions_ab)
check("虚拟注入跳过 active_bash=True 的父: count 不注入",
      r_ab.get(PARENT_SID, {}).get("active_subagent_count") == 0)

# --- 13-12: 非 rescue Codex（有 parent_sid）也触发虚拟注入 ---
PARENT_SID2 = "vb-nonrescue-parent"
CX_NR = "codex:vb-nonrescue"
sessions_nr = {
    PARENT_SID2: mk_sess(active_subagent_count=0, active_bash=False),
    CX_NR: {
        "status": "running", "is_primary": True,
        "source": "codex", "last_update": now_iso(), "last_prompt": "normal prompt",
        "parent_sid": PARENT_SID2,
    },
}
r_nr = apply_state_filter(sessions_nr)
check("非rescue Codex(有 parent_sid): 也触发父虚拟注入",
      r_nr.get(PARENT_SID2, {}).get("active_subagent_count") == 1)

# ════════════════════════════════════════════════════════════════════════════
# 14. SessionEnd 与 CwdChanged
# ════════════════════════════════════════════════════════════════════════════
section("14. SessionEnd 与 CwdChanged")

SID = "t-end-cwd"
cleanup(SID)

# SessionEnd 删除 session
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
check("SessionEnd setup: session 存在", get_sess(SID) != {})
hook({"session_id": SID, "hook_event_name": "SessionEnd", "cwd": "C:/dev/P"})
check("SessionEnd: session 被删除", SID not in load_state()["sessions"])

# Codex SessionEnd 删除 codex session
hook({"session_id": SID, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/P", "model": "m"}, source="codex")
check("Codex SessionEnd setup: codex session 存在",
      f"codex:{SID}" in load_state()["sessions"])
hook({"session_id": SID, "hook_event_name": "SessionEnd",
      "cwd": "C:/dev/P"}, source="codex")
check("Codex SessionEnd: codex session 被删除",
      f"codex:{SID}" not in load_state()["sessions"])

# CwdChanged 更新 cwd/cwd_name
hook({"session_id": SID, "hook_event_name": "SessionStart",
      "cwd": "C:/dev/Original", "model": "m"})
hook({"session_id": SID, "hook_event_name": "CwdChanged", "cwd": "C:/dev/NewProject"})
s = get_sess(SID)
check("CwdChanged: cwd 更新", s.get("cwd") == "C:/dev/NewProject")
check("CwdChanged: cwd_name 更新", s.get("cwd_name") == "NewProject")

# CwdChanged 不影响 status
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/NewProject", "prompt": "x"})
hook({"session_id": SID, "hook_event_name": "CwdChanged", "cwd": "C:/dev/Another"})
s = get_sess(SID)
check("CwdChanged 不影响 status", s.get("status") == "running")
check("CwdChanged running 时也更新", s.get("cwd") == "C:/dev/Another")

cleanup(SID)

# CwdChanged cwd 缺失 → 不创建空 session
SID2 = "t-cwdguard"
cleanup(SID2)
hook({"session_id": SID2, "hook_event_name": "CwdChanged"})
check("CwdChanged(cwd缺失): 不创建空 session",
      SID2 not in load_state()["sessions"])

cleanup(SID, SID2)

# ════════════════════════════════════════════════════════════════════════════
# 15. 后台 subagent 跨 turn 保持蓝色
# ════════════════════════════════════════════════════════════════════════════
section("15. 后台 subagent 跨 turn 保持蓝色")

SID = "t-bg-persist"
cleanup(SID)

# Turn 1：派出后台 subagent，Claude 完成自己的回复
hook({"session_id": SID, "hook_event_name": "SessionStart", "cwd": "C:/dev/P", "model": "m"})
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "C:/dev/P", "prompt": "dispatch agent"})
hook({"session_id": SID, "hook_event_name": "SubagentStart",
      "cwd": "C:/dev/P", "agent_type": "codex-rescue", "agent_id": "agent-bg-001"})
hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
s = get_sess(SID)
check("Turn1 Stop 后: BLUE (idle+count=1)", cname(s) == "BLUE")

# Turn 2：用户发新消息，后台 agent 仍在运行（SubagentStop 尚未触发）
hook({"session_id": SID, "hook_event_name": "UserPromptSubmit",
      "cwd": "C:/dev/P", "prompt": "how is it going?"})
hook({"session_id": SID, "hook_event_name": "Stop", "cwd": "C:/dev/P"})
s = get_sess(SID)
check("Turn2 Stop 后: 仍为 BLUE（后台 agent 未结束）",
      cname(s) == "BLUE", f"got {cname(s)}, count={s.get('active_subagent_count')}")

# 后台 agent 完成，SubagentStop 触发
hook({"session_id": SID, "hook_event_name": "SubagentStop",
      "cwd": "C:/dev/P", "agent_id": "agent-bg-001"})
s = get_sess(SID)
check("SubagentStop 后: GREEN (agent 已结束)", cname(s) == "GREEN")

cleanup(SID)

# ════════════════════════════════════════════════════════════════════════════
# 结果汇总
# ════════════════════════════════════════════════════════════════════════════
print(f"\n{'═'*60}")
print(f"  结果: {PASS} 通过  {FAIL} 失败  共 {PASS+FAIL} 项")
print(f"{'═'*60}")
sys.exit(0 if FAIL == 0 else 1)
