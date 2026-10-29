@echo off
rem Beendet die im Hintergrund laufende Rezepte-App (Python-Prozess auf Port 8642).
powershell -NoProfile -Command ^
  "$c = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8642 -State Listen -ErrorAction SilentlyContinue;" ^
  "$p = $c | ForEach-Object { Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } | Where-Object { $_.Name -like 'python*' };" ^
  "if ($p) { $p | Stop-Process -Force; 'Rezepte-App wurde beendet.' } else { 'Rezepte-App laeuft nicht.' }"
timeout /t 3 >nul
