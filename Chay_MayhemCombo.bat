@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 "%~dp0app.pyw"
  exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0app.pyw"
  exit /b
)
where python >nul 2>nul
if %errorlevel%==0 (
  start "" python "%~dp0app.pyw"
  exit /b
)
echo.
echo  Chua cai Python. Hay cai Python 3 tu python.org (nho tick "Add python.exe to PATH"),
echo  sau do chay lai file nay. Dang mo trang tai Python...
start "" "https://www.python.org/downloads/windows/"
pause
