@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  [最终打包] 构建独立 exe 与便携迁移包
echo  请在界面调整全部完成后才执行（耗时约 2-5 分钟）
echo ============================================
python build_portable.py
pause
