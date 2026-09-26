@echo off
"%LAB_WATCH_PYTHON%" -u -m tools.lab_launcher.watch %LAB_WATCH_KIND%
if errorlevel 1 echo Observador encerrado com erro. Consulte a mensagem acima.
