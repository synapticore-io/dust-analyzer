# MCP stdio: uv run (project env, syncs before run). See https://docs.astral.sh/uv/concepts/projects/run/
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path $uv)) { $uv = 'uv' }
& $uv run python -m dust_analyzer --mcp
