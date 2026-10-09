@echo off
setlocal
cd /d "%~dp0"
set PATH=%~dp0;%PATH%
title MP4 Chapter Injector
python "%~dp0mp4_chapter_tool.py"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Execution failed with code %ERRORLEVEL%
    pause
)
