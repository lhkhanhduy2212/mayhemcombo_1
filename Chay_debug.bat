@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Chay Mayhem Combo o che do xem loi (cua so nay se hien loi neu co)...
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0app.pyw"
) else (
  python "%~dp0app.pyw"
)
echo.
echo Log: %APPDATA%\MayhemCombo\log.txt
pause
