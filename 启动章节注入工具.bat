@echo off
setlocal
cd /d "%~dp0"
set PATH=%~dp0;%PATH%
title MP4 章节信息批量注入工具

echo ======================================================
echo    正在启动 MP4 章节信息批量注入工具...
echo ======================================================

python "%~dp0mp4_chapter_tool.py"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [错误] 程序运行遇到异常，错误代码: %ERRORLEVEL%
    echo 请检查是否已正确安装 Python 并配置到环境变量中。
    pause
)
