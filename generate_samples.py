# -*- coding: utf-8 -*-
"""
样例生成模块：自动生成可用于测试章节注入的 MP4 视频与同名章节文本文件
"""

import os
import subprocess
import sys


def get_ffmpeg_cmd() -> str:
    """获取 ffmpeg 可执行文件路径，优先使用程序(exe)同目录下的 ffmpeg.exe"""
    if getattr(sys, 'frozen', False):
        current_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        current_dir = os.path.dirname(os.path.abspath(__file__))
    local_ffmpeg = os.path.join(current_dir, "ffmpeg.exe")
    if os.path.isfile(local_ffmpeg):
        return local_ffmpeg
    return "ffmpeg"


def generate_sample_suite(output_dir: str = "."):
    """
    在指定目录下生成样例 MP4 视频与对应的章节文本
    """
    ffmpeg_bin = get_ffmpeg_cmd()
    os.makedirs(output_dir, exist_ok=True)
    
    # 样例 1: 标准 OGM 格式 (20秒测试视频)
    vid1_name = "sample_tutorial"
    vid1_path = os.path.join(output_dir, f"{vid1_name}.mp4")
    txt1_path = os.path.join(output_dir, f"{vid1_name}.txt")
    
    ogm_content = """CHAPTER01=00:00:00.000
CHAPTER01NAME=01-课程引言与概要
CHAPTER02=00:00:05.000
CHAPTER02NAME=02-核心原理深入剖析
CHAPTER03=00:00:10.000
CHAPTER03NAME=03-代码实战演示环节
CHAPTER04=00:00:15.000
CHAPTER04NAME=04-课程回顾与课后答疑
"""
    with open(txt1_path, 'w', encoding='utf-8') as f:
        f.write(ogm_content)
        
    print(f"[+] 已生成章节文本: {txt1_path}")

    # 用 ffmpeg 生成带色彩渐变和测试音频的 20 秒 MP4
    if not os.path.exists(vid1_path):
        print(f"[*] 正在生成样例视频: {vid1_path} (时长: 20s)...")
        # 使用 testsrc2 滤镜 + 440Hz 测试音频
        cmd1 = [
            ffmpeg_bin, '-y',
            '-f', 'lavfi', '-i', 'testsrc2=duration=20:size=960x540:rate=25',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=20:sample_rate=44100',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast',
            '-c:a', 'aac', '-b:a', '128k',
            vid1_path
        ]
        res1 = subprocess.run(
            cmd1, capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if res1.returncode == 0:
            print(f"[+] 样例视频生成成功: {vid1_path}")
        else:
            print(f"[-] 样例视频生成失败:\n{res1.stderr}")
    else:
        print(f"[!] 样例视频已存在，跳过生成: {vid1_path}")

    # 样例 2: 常用冒号时间戳格式 (15秒测试视频，测试多文件批量识别)
    vid2_name = "sample_showcase"
    vid2_path = os.path.join(output_dir, f"{vid2_name}.mp4")
    txt2_path = os.path.join(output_dir, f"{vid2_name}.txt")

    simple_content = """00:00:00.000 精彩片头
00:00:04.500 第一章节：产品特色
00:00:09.000 第二章节：技术架构
00:00:12.500 第三章节：未来展望与致谢
"""
    with open(txt2_path, 'w', encoding='utf-8') as f:
        f.write(simple_content)
    print(f"[+] 已生成章节文本: {txt2_path}")

    if not os.path.exists(vid2_path):
        print(f"[*] 正在生成样例视频: {vid2_path} (时长: 15s)...")
        cmd2 = [
            ffmpeg_bin, '-y',
            '-f', 'lavfi', '-i', 'smptebars=duration=15:size=960x540:rate=25',
            '-f', 'lavfi', '-i', 'sine=frequency=523:duration=15:sample_rate=44100',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast',
            '-c:a', 'aac', '-b:a', '128k',
            vid2_path
        ]
        res2 = subprocess.run(
            cmd2, capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if res2.returncode == 0:
            print(f"[+] 样例视频生成成功: {vid2_path}")
        else:
            print(f"[-] 样例视频生成失败:\n{res2.stderr}")
    else:
        print(f"[!] 样例视频已存在，跳过生成: {vid2_path}")


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    generate_sample_suite(target)
