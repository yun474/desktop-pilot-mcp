@echo off
rem Stop Desktop Pilot MCP instances running in the background (started by autostart).
powershell -NoProfile -ExecutionPolicy Bypass -Command "$procs = Get-CimInstance Win32_Process -Filter \"Name = 'pythonw.exe'\" | Where-Object { $_.CommandLine -like '*desktop_pilot_mcp*' }; if ($procs) { $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; 'Stopped process ' + $_.ProcessId } } else { 'No background instance is running.' }"
pause
