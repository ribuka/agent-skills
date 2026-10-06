# 設定ファイルから model / effort を解決して 1 行で出力する。
#   Claude: model は -Model で渡す（システムプロンプトにある自分のモデル ID）。
#           effort は CLAUDE_CODE_EFFORT_LEVEL -> modelSettings.<model>.effortLevel -> effortLevel。
#   Codex:  model / effort とも $CODEX_HOME/config.toml（-Model を渡せばそちらを優先）。
param(
    [Parameter(Mandatory)][ValidateSet('claude', 'codex')][string]$Agent,
    [string]$Model
)
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$Model = $Model -replace '\[.*\]$', ''   # "claude-opus-5-5[1m]" -> "claude-opus-5-5"

if ($Agent -eq 'claude') {
    $configDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }
    $settings = Get-Content (Join-Path $configDir 'settings.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $Model) { $Model = $env:ANTHROPIC_MODEL }
    if (-not $Model) { $Model = $settings.model }
    $effort = $env:CLAUDE_CODE_EFFORT_LEVEL
    if (-not $effort -and $Model) { $effort = $settings.modelSettings.$Model.effortLevel }
    if (-not $effort) { $effort = $settings.effortLevel }
} else {
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
    $config = Get-Content (Join-Path $codexHome 'config.toml') -Raw -Encoding UTF8
    if (-not $Model -and $config -match '(?m)^model\s*=\s*"([^"]+)"') { $Model = $Matches[1] }
    if ($config -match '(?m)^model_reasoning_effort\s*=\s*"([^"]+)"') { $effort = $Matches[1] }
}

if (-not $Model) { $Model = 'unknown' }
if (-not $effort) { $effort = 'default' }
"🧠 model: $Model / effort: $effort"
