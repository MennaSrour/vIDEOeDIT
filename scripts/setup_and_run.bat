@echo off
setlocal
cd /d "%~dp0.."
where ffmpeg >nul 2>&1 || goto missingffmpeg
where ffprobe >nul 2>&1 || goto missingffmpeg
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>&1
    if errorlevel 1 (
        python -m venv .venv || exit /b 1
    ) else (
        py -3 -m venv .venv || exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || exit /b 1
if "%~1"=="--setup-only" exit /b 0
if not defined REELSFORGE_BIND set "REELSFORGE_BIND=127.0.0.1"
".venv\Scripts\python.exe" -m streamlit run app.py --server.address "%REELSFORGE_BIND%" %*
exit /b %errorlevel%

:missingffmpeg
echo Install FFmpeg including ffprobe, add it to PATH, and reopen this terminal. See README.md.
exit /b 1
