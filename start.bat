@echo off
rem Start Desktop Pilot MCP in a console window.
rem First run: installs dependencies with uv and creates config.toml with a random token.
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv not found. Install it first: https://docs.astral.sh/uv/
    pause
    exit /b 1
)
set PYTHONUTF8=1
uv run --no-dev desktop-pilot-mcp --config "%~dp0config.toml"
pause
