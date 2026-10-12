---
name: show-model
description: Show the model and reasoning effort currently configured for this agent session (Claude Code or Codex) as one line. Use when the user asks which model / effort is in use, e.g. "model と effort を出して", "いまのモデルは？", or right after switching models.
---

# Show model / effort

Resolve the current model and effort from the agent's own config files and
print them as one line.

| You are     | Run |
|-------------|-----|
| Claude Code | `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.agents/skills/show-model/scripts/show_model.ps1 -Agent claude -Model <your exact model ID>` |
| Codex       | `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.agents/skills/show-model/scripts/show_model.ps1 -Agent codex` |

- Claude Code: pass your exact model ID from your system prompt
  (e.g. `claude-opus-5-5`), not an alias such as `opus`. The script looks up
  the effort for that model in `settings.json`.
- Codex: the script reads `model` and `model_reasoning_effort` from
  `$CODEX_HOME/config.toml` (Orca sets `CODEX_HOME` to its own runtime home).

Put the script's output line verbatim as the first line of your reply, e.g.

```text
🧠 model: claude-opus-5-5 / effort: medium
```

Values come from config files, so a `--model` / `--effort` flag given at launch
is not reflected. Say so if the user may have used one.
