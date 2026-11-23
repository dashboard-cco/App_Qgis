@echo off
REM Copia o plugin para o perfil do QGIS (UMA cópia só). Feche o QGIS antes.
set DEST=%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\qgis_claude_ai
if exist "%DEST%" rmdir /s /q "%DEST%"
xcopy /e /i /y "%~dp0qgis_claude_ai" "%DEST%"
REM remove a cópia solta antiga (python\qgis_claude_ai), que causava versões divergentes
if exist "%APPDATA%\QGIS\QGIS3\profiles\default\python\qgis_claude_ai" rmdir /s /q "%APPDATA%\QGIS\QGIS3\profiles\default\python\qgis_claude_ai"
echo Instalado em %DEST%. Abra o QGIS e ative o plugin em Complementos.
pause
