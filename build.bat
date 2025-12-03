@echo off
setlocal

REM ==============================
REM Build script para HTP con PyInstaller
REM ==============================

cd /d %~dp0

echo Limpiando carpetas anteriores...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

echo Ejecutando PyInstaller con htp.spec...
pyinstaller htp.spec

echo.
echo Build completado. Ejecutable en:
echo   dist\HTP\HTP.exe
echo.
pause
endlocal
