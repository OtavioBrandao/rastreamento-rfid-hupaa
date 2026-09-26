@echo off
title RFID %~3
set "PYTHONIOENCODING=utf-8"
"%~1" -u -m tools.lab_launcher.watch %~2 --session-file "%~4"
if errorlevel 1 echo Observador encerrado com erro. Consulte a mensagem acima.
