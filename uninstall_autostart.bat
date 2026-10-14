@echo off
rem Remove the startup shortcut created by install_autostart.bat.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = [Environment]::GetFolderPath('Startup') + '\DesktopPilotMCP.lnk'; if (Test-Path $p) { Remove-Item $p; 'Autostart removed.' } else { 'Autostart is not installed.' }"
pause
