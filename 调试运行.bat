@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  [调试模式] 直接从源码运行界面（无需打包）
echo  改完代码后关掉窗口重新双击即可看到效果
echo ============================================
python mp4_chapter_tool.py
if errorlevel 1 pause
