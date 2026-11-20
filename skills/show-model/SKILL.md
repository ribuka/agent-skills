---
name: show-model
description: Show the model and reasoning effort currently configured for this agent session (Claude Code or Codex) as one line. Use when the user asks which model / effort is in use, e.g. "model と effort を出して", "いまのモデルは？", or right after switching models.
---

# Show model / effort

Resolve the current model and effort for this agent and print them as one
line.

| You are     | Run |
|-------------|-----|
| Claude Code | `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.agents/skills/show-model/scripts/show_model.ps1 -Agent claude -Model <your exact model ID>` |
| Codex       | `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.agents/skills/show-model/scripts/show_model.ps1 -Agent codex` |

- Claude Code: pass your exact model ID from your system prompt
  (e.g. `claude-opus-5-5`), not an alias such as `opus`. The script takes the
  effort from `CLAUDE_CODE_EFFORT_LEVEL` first, then from `settings.json`
  (the effort for that model, then the common `effortLevel`).
- Codex: the script reads `model` and `model_reasoning_effort` from
  `$CODEX_HOME/config.toml` (Orca sets `CODEX_HOME` to its own runtime home).

Put the script's output line verbatim as the first line of your reply, e.g.

```text
🧠 model: claude-opus-5-5 / effort: medium
```

What the line reflects depends on the agent:

- Claude Code: the model comes from your own model ID in the system prompt,
  so a `--model` flag at launch or a `/model` switch in the session is
  reflected. The effort comes from `CLAUDE_CODE_EFFORT_LEVEL` and
  `settings.json`, so an effort set only for this session (e.g. `--effort` at
  launch) is not reflected. Say so about the effort if the user may have set
  one that way.
- Codex: both the model and the effort are read from
  `$CODEX_HOME/config.toml`, so a model or effort override given at launch is
  not reflected. Say so if the user may have used one.
