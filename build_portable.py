# -*- coding: utf-8 -*-
"""
一键打包脚本：将 MP4 章节注入工具构建为 Windows 独立可执行程序 + 便携迁移包

产物：
  dist/MP4ChapterTool_便携版/
      ├── MP4ChapterTool.exe        图形界面版（双击运行）
      ├── MP4ChapterTool-CLI.exe    命令行版
      ├── ffmpeg.exe / ffprobe.exe  已内置 FFmpeg
      └── 使用说明.txt
  dist/MP4章节注入工具_便携版_x64.zip   最终迁移包

用法:  python build_portable.py
"""

import os
import sys
import shutil
import subprocess
import zipfile

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(WORKSPACE, "dist")
ASSETS = os.path.join(WORKSPACE, "assets")
ICON = os.path.join(ASSETS, "icon.ico")
PKG_NAME = "MP4ChapterTool_便携版"
PKG_DIR = os.path.join(DIST, PKG_NAME)
ZIP_PATH = os.path.join(DIST, "MP4章节注入工具_便携版_x64.zip")

# 本机 winget 安装的 FFmpeg 备用查找路径（优先使用 PATH 中的）
FFMPEG_FALLBACK_BIN = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.0.1-full_build\bin",
)


def step(msg: str):
    print(f"\n{'=' * 62}\n[步骤] {msg}\n{'=' * 62}", flush=True)


def make_icon():
    """用 PIL 生成程序图标：蓝色渐变底 + 播放三角 + 章节分段进度条"""
    from PIL import Image, ImageDraw

    os.makedirs(ASSETS, exist_ok=True)
    S = 256
    # 蓝色垂直渐变底板
    grad = Image.new('RGBA', (S, S))
    gd = ImageDraw.Draw(grad)
    top, bot = (33, 150, 243), (13, 71, 161)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)],
                fill=(int(top[0] + (bot[0] - top[0]) * t),
                      int(top[1] + (bot[1] - top[1]) * t),
                      int(top[2] + (bot[2] - top[2]) * t), 255))
    # 圆角蒙版
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=255)
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # 白色播放三角
    d.polygon([(100, 54), (100, 152), (178, 103)], fill=(255, 255, 255, 255))
    # 底部章节分段进度条（4 段，第 2 段橙色高亮 = 当前章节）
    for i, x in enumerate((36, 88, 140, 192)):
        color = (255, 171, 64, 255) if i == 1 else (255, 255, 255, 110)
        d.rounded_rectangle([x, 176, x + 40, 196], radius=9, fill=color)
    img.save(ICON, format='ICO',
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"[+] 图标已生成: {ICON}", flush=True)


def build_exe(name: str, console: bool):
    """调用 PyInstaller 构建单文件 exe"""
    flags = [
        "--noconfirm", "--clean", "--onefile",
        f"--name={name}", f"--icon={ICON}",
        f"--add-data={ICON};assets",   # 把图标内置进 exe，供运行时设置窗体/任务栏图标
        "--windowed" if not console else "--console",
        os.path.join(WORKSPACE, "mp4_chapter_tool.py"),
    ]
    cmd = [sys.executable, "-m", "PyInstaller"] + flags
    print("[cmd]", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=WORKSPACE, check=True)


def locate_ff_bin(tool: str) -> str:
    """定位本机 ffmpeg/ffprobe：优先 PATH，其次 winget 默认安装路径"""
    p = shutil.which(tool)
    if p:
        return p
    guess = os.path.join(FFMPEG_FALLBACK_BIN, f"{tool}.exe")
    if os.path.isfile(guess):
        return guess
    raise FileNotFoundError(
        f"找不到 {tool}.exe —— 请先安装 FFmpeg，或手动将 {tool}.exe 放入: {PKG_DIR}")


def write_readme():
    content = """\
MP4 章节注入工具 便携版
================================================================

【这是什么】
把章节信息（OGM 格式或时间戳格式的文本文件）无损注入 MP4 / M4V / MOV
视频，兼容 PotPlayer / VLC 播放器的章节选择功能。
注入过程不重新编码（-c copy），原画质与音质完全不变。

【目录内容】
  MP4ChapterTool.exe        图形界面版 —— 双击即可运行
  MP4ChapterTool-CLI.exe    命令行版 —— 适合脚本 / 批量任务
  ffmpeg.exe / ffprobe.exe  已内置，无需另外安装
                            （删除后程序会自动改用系统 PATH 中的 ffmpeg）

【图形界面版用法】
  1. 双击 MP4ChapterTool.exe
  2. 选择视频目录，默认开启"搜索子目录(递归)"，点"重新扫描"（自动匹配各级子目录下的同名章节文本并解析）
  3. 点"一键批量注入章节"，结果输出到视频目录下的 with_chapters 子目录（自动保持原目录相对层级）
     （勾选"覆盖原视频"则原地覆盖，原文件自动保留 .bak 备份）
  4. 支持鼠标右键条目快捷播放、打开所在目录或查看章节文本
  5. 点击"关于"或菜单栏"帮助 -> 关于"查看软件信息与支持

【章节文本格式】（与视频同名，如 movie.mp4 对应 movie.txt）
  格式一 OGM:
      CHAPTER01=00:00:00.000
      CHAPTER01NAME=开场
      CHAPTER02=00:02:30.500
      CHAPTER02NAME=第一部分
  格式二 时间戳:
      00:00:00.000 开场
      00:02:30.500 第一部分

【命令行版用法】
  :: 为目录下所有视频注入章节（输出到 with_chapters/）
  MP4ChapterTool-CLI.exe --dir "D:\\视频目录"

  :: 递归扫描所有子目录并注入（输出时保持子目录相对层级）
  MP4ChapterTool-CLI.exe --dir "D:\\视频目录" -r

  :: 指定输出目录
  MP4ChapterTool-CLI.exe --dir "D:\\视频目录" --output "D:\\输出"

  :: 覆盖原视频（自动生成 .bak 备份）
  MP4ChapterTool-CLI.exe --dir "D:\\视频目录" --overwrite

  :: 生成演示样例视频与章节文件（测试用）
  MP4ChapterTool-CLI.exe --dir "D:\\测试" --generate-sample

【关于与联系支持】
  设计者 (Designer): Jiansheng Guo
  联系邮箱 (Email): ozparse@outlook.com

【常见问题】
  * 首次运行若弹出 Windows SmartScreen 蓝色提示：
    点"更多信息" -> "仍要运行"即可。
  * 本包已内置 ffmpeg / ffprobe，拷贝到任何 Windows 10/11 x64
    电脑均可直接使用，无需安装 Python 或任何运行库。
  * 整个文件夹可放 U 盘 / 移动硬盘随处运行，删掉不需要的文件
    也不会影响其余功能。
"""
    with open(os.path.join(PKG_DIR, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(content)
    print("[+] 使用说明已写入", flush=True)


def assemble_package():
    """组装便携包目录"""
    step(f"组装便携包目录: {PKG_DIR}")
    os.makedirs(PKG_DIR, exist_ok=True)

    for exe in ("MP4ChapterTool.exe", "MP4ChapterTool-CLI.exe"):
        src = os.path.join(DIST, exe)
        if not os.path.isfile(src):
            raise FileNotFoundError(f"缺少构建产物: {src}")
        dst = os.path.join(PKG_DIR, exe)
        shutil.move(src, dst)
        print(f"[+] {exe}  ({os.path.getsize(dst) / 1048576:.1f} MB)")

    for tool in ("ffmpeg.exe", "ffprobe.exe"):
        dst = os.path.join(PKG_DIR, tool)
        if os.path.isfile(dst):
            print(f"[=] {tool} 已存在，跳过复制")
            continue
        src = locate_ff_bin(tool[:-4])
        size_mb = os.path.getsize(src) / 1048576
        print(f"[+] 复制 {tool} ({size_mb:.0f} MB) <- {src}")
        shutil.copy2(src, dst)

    write_readme()


def make_zip():
    """压缩为可迁移 zip 包"""
    step(f"生成迁移 zip 包: {ZIP_PATH}")
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for fn in sorted(os.listdir(PKG_DIR)):
            fp = os.path.join(PKG_DIR, fn)
            zf.write(fp, f"{PKG_NAME}/{fn}")
            print(f"    + {fn}  ({os.path.getsize(fp) / 1048576:.1f} MB)")
    print(f"[√] 完成: {ZIP_PATH}  ({os.path.getsize(ZIP_PATH) / 1048576:.1f} MB)", flush=True)


def main():
    step("1/4 生成图标")
    make_icon()

    step("2/4 构建 GUI exe (MP4ChapterTool.exe)")
    build_exe("MP4ChapterTool", console=False)

    step("3/4 构建 CLI exe (MP4ChapterTool-CLI.exe)")
    build_exe("MP4ChapterTool-CLI", console=True)

    step("4/4 组装便携包")
    assemble_package()
    make_zip()

    print("\n全部完成 [OK]", flush=True)


if __name__ == "__main__":
    main()
