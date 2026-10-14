@echo off
rem Run Desktop Pilot MCP silently in the background after you log in to Windows.
rem It creates a shortcut in your Startup folder (no admin rights needed).
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo [ERROR] Environment not ready. Run start.bat once first.
    pause
    exit /b 1
)
if not exist "%~dp0config.toml" (
    echo [ERROR] config.toml not found. Run start.bat once first.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup') + '\DesktopPilotMCP.lnk'); $s.TargetPath = '%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments = '-m desktop_pilot_mcp'; $s.WorkingDirectory = '%~dp0'; $s.Save()"
if errorlevel 1 (
    echo [ERROR] Failed to create the startup shortcut.
    pause
    exit /b 1
)
echo Autostart installed. It will start after your next login.
echo Logs: %~dp0desktop-pilot.log
pause
