# VULPHEX coder: gives a FOX bot Claude Code's body (run commands, read/write/edit files, build and fix code) with YOUR
# uncensored brain behind it and a security skill loaded. Same idea as Mira: Claude Code is the hands; the brain is a
# model you choose (agent.json base_url/model, e.g. Mira's Kaggle tunnel or a local Ollama Anthropic endpoint). This is
# how FOX FORGE actually writes a fix, FOX AUDITOR reasons over code, and the red bots script work against a target YOU
# declared. It runs `claude` headless and streams each step. Authorization is yours; every run is audited by the core.
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "skills")


def config():
    try: cfg = json.load(open(os.path.join(HERE, "agent.json")))
    except (OSError, ValueError): cfg = {}
    cfg.setdefault("allowed_tools", ["Bash", "Read", "Write", "Edit", "Glob", "Grep"])
    cfg.setdefault("timeout_s", 1800)
    return cfg


def skill_text(skill):
    p = os.path.join(SKILLS, skill, "SKILL.md")
    try: return open(p).read()
    except OSError: return ""


def have_claude():
    import shutil
    return shutil.which(os.environ.get("VULPHEX_CLAUDE_BIN", "claude")) is not None


def build_cmd(mission, cfg, skill, bot=""):
    """The headless Claude Code command: the bot's brain, its tools, and its skill as the system prompt."""
    model = cfg.get("model") or ""
    sysp = (f"You are {bot or 'a VULPHEX FOX security bot'}. Do the security engineering task below for systems Mark owns "
            f"or is authorized to test. Be precise, show commands and results, and make only scoped changes.\n\n" + skill_text(skill)).strip()
    cmd = [os.environ.get("VULPHEX_CLAUDE_BIN", "claude"), "-p", mission, "--output-format", "stream-json", "--verbose",
           "--allowedTools", *cfg.get("allowed_tools", []), "--append-system-prompt", sysp]
    if model: cmd += ["--model", model]
    return cmd


def env_for(cfg):
    env = dict(os.environ)
    base = cfg.get("base_url") or os.environ.get("VULPHEX_BRAIN_URL")
    tok = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("VULPHEX_BRAIN_TOKEN")
    if base:
        env["ANTHROPIC_BASE_URL"] = base
        if tok: env["ANTHROPIC_AUTH_TOKEN"] = tok; env["ANTHROPIC_API_KEY"] = ""
        if cfg.get("model"):
            for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
                env[k] = cfg["model"]
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def run(mission, cwd=".", skill="fox-fix", bot="", cfg=None, on_event=None, spawn=None):
    """Run the coding agent. Returns {ok, summary, steps}. `spawn` is injectable for tests. Never raises."""
    cfg = cfg or config()
    if not have_claude() and spawn is None:
        return {"ok": False, "summary": "Claude Code isn't installed. Install it (curl -fsSL https://claude.ai/install.sh | bash), "
                "then set the uncensored brain in security/agent.json (base_url/model).", "steps": []}
    cmd = build_cmd(mission, cfg, skill, bot)
    steps, summary = [], ""
    try:
        proc = (spawn or _spawn)(cmd, cwd, cfg["timeout_s"])
        for line in proc:
            try: ev = json.loads(line)
            except ValueError: continue
            if ev.get("type") == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use":
                        step = {"tool": b.get("name"), "input": str((b.get("input") or {}).get("command") or (b.get("input") or {}).get("file_path") or "")[:200]}
                        steps.append(step); on_event and on_event("step", step)
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        on_event and on_event("say", b["text"])
            elif ev.get("type") == "result":
                summary = ev.get("result") or ""
        return {"ok": bool(summary), "summary": summary or "(the agent finished without a summary)", "steps": steps}
    except Exception as e:
        return {"ok": False, "summary": f"agent error: {type(e).__name__}: {e}", "steps": steps}


def _spawn(cmd, cwd, timeout_s):
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return iter(p.stdout.readline, "")
