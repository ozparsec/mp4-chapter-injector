# -*- coding: utf-8 -*-
"""
章节文本解析与 FFMETADATA 生成模块
支持 OGM 格式 (CHAPTER01=... / CHAPTER01NAME=...) 以及常见简易时间戳格式。
"""

import re
import os
import sys
import subprocess
import json
from typing import List, Dict, Optional, Tuple


def parse_timestamp_to_ms(time_str: str) -> int:
    """
    将时间字符串转换为毫秒
    支持格式:
      HH:MM:SS.mmm
      HH:MM:SS,mmm
      HH:MM:SS
      MM:SS.mmm
      MM:SS
    """
    time_str = time_str.strip().replace(',', '.')
    parts = time_str.split(':')
    
    if len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        s_parts = parts[2].split('.')
        s = int(s_parts[0])
        ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
        return (h * 3600 + m * 60 + s) * 1000 + ms
    elif len(parts) == 2:
        m = int(parts[0])
        s_parts = parts[1].split('.')
        s = int(s_parts[0])
        ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
        return (m * 60 + s) * 1000 + ms
    elif len(parts) == 1:
        s_parts = parts[0].split('.')
        s = int(s_parts[0])
        ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
        return s * 1000 + ms
    else:
        raise ValueError(f"无法识别的时间格式: {time_str}")


def ms_to_timestamp(ms: int) -> str:
    """毫秒转换为 HH:MM:SS.mmm 格式"""
    total_sec, milli = divmod(ms, 1000)
    hours, remainder = divmod(total_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milli:03d}"


def read_text_with_auto_encoding(file_path: str) -> str:
    """尝试以常见编码自动读取文本文件"""
    encodings = ['utf-8', 'utf-8-sig', 'gb18030', 'gbk', 'big5', 'latin1']
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    # 兜底
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def parse_chapters_content(content: str) -> List[Dict[str, any]]:
    """
    解析章节文本内容，支持：
    1. 标准 OGM 格式:
       CHAPTER01=00:00:00.000
       CHAPTER01NAME=开场
       CHAPTER02=00:02:30.500
       CHAPTER02NAME=教程A
    2. 简易时间戳格式:
       00:00:00.000 开场
       00:02:30.500 教程A
       或 00:02:30 - 教程A
    """
    chapters = []
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    # 模式1: OGM 格式检测
    ogm_time_pattern = re.compile(r'^CHAPTER(\d+)=([0-9:.,]+)$', re.IGNORECASE)
    ogm_name_pattern = re.compile(r'^CHAPTER(\d+)NAME=(.*)$', re.IGNORECASE)
    
    times_dict = {}
    names_dict = {}
    
    for line in lines:
        m_time = ogm_time_pattern.match(line)
        if m_time:
            idx = int(m_time.group(1))
            times_dict[idx] = m_time.group(2).strip()
            continue
        m_name = ogm_name_pattern.match(line)
        if m_name:
            idx = int(m_name.group(1))
            names_dict[idx] = m_name.group(2).strip()
            continue
            
    if times_dict:
        # 按照章节编号排序
        for idx in sorted(times_dict.keys()):
            time_str = times_dict[idx]
            name_str = names_dict.get(idx, f"Chapter {idx}")
            try:
                ms = parse_timestamp_to_ms(time_str)
                chapters.append({
                    "index": idx,
                    "start_ms": ms,
                    "title": name_str or f"Chapter {idx}"
                })
            except Exception as e:
                pass
        if chapters:
            return chapters

    # 模式2: 常见简易格式 (时间戳 + 标题)
    # 如: "00:00:00.000 开场" 或 "00:00:00 - 开场"
    simple_pattern = re.compile(r'^([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?(?:[.,][0-9]{1,3})?)\s*[-—:]?\s*(.*)$')
    for idx, line in enumerate(lines, 1):
        m = simple_pattern.match(line)
        if m:
            time_str = m.group(1).strip()
            name_str = m.group(2).strip() or f"Chapter {idx}"
            try:
                ms = parse_timestamp_to_ms(time_str)
                chapters.append({
                    "index": idx,
                    "start_ms": ms,
                    "title": name_str
                })
            except Exception:
                continue

    # 按时间戳重新升序排序
    chapters.sort(key=lambda x: x["start_ms"])
    return chapters


def escape_ffmetadata(text: str) -> str:
    """
    FFMETADATA 格式中的特殊字符转义：
    '=', ';', '#', '\' 以及换行符必须进行转义
    """
    text = text.replace('\\', '\\\\')
    text = text.replace('=', '\\=')
    text = text.replace(';', '\\;')
    text = text.replace('#', '\\#')
    text = text.replace('\n', '\\\n')
    return text


def build_ffmetadata_content(chapters: List[Dict[str, any]], total_duration_ms: Optional[int] = None) -> str:
    """
    根据章节列表生成 FFMETADATA1 文件内容
    如果提供了 total_duration_ms，最后一章将以该时长作为 end_ms，
    否则最后一章 end_ms = start_ms + 10分钟
    """
    if not chapters:
        return ";FFMETADATA1\n"
    
    # 确保排序
    sorted_chapters = sorted(chapters, key=lambda c: c["start_ms"])
    
    meta_lines = [";FFMETADATA1"]
    
    for i in range(len(sorted_chapters)):
        curr_chap = sorted_chapters[i]
        start_ms = curr_chap["start_ms"]
        
        # 计算结束时间
        if i + 1 < len(sorted_chapters):
            end_ms = sorted_chapters[i + 1]["start_ms"]
            # 防止相邻时间戳相同导致播放器异常
            if end_ms <= start_ms:
                end_ms = start_ms + 1000
        else:
            if total_duration_ms and total_duration_ms > start_ms:
                end_ms = total_duration_ms
            else:
                end_ms = start_ms + 600000  # 默认加10分钟
                
        title = escape_ffmetadata(curr_chap.get("title", f"Chapter {i+1}"))
        
        meta_lines.append("")
        meta_lines.append("[CHAPTER]")
        meta_lines.append("TIMEBASE=1/1000")
        meta_lines.append(f"START={start_ms}")
        meta_lines.append(f"END={end_ms}")
        meta_lines.append(f"title={title}")
        
    meta_lines.append("")
    return "\n".join(meta_lines)


def _app_dir() -> str:
    """程序所在目录（兼容 PyInstaller 打包运行与源码直接运行）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_ffprobe_cmd() -> str:
    """获取 ffprobe 可执行文件路径，优先使用程序(exe)同目录下的 ffprobe.exe"""
    local_ffprobe = os.path.join(_app_dir(), "ffprobe.exe")
    if os.path.isfile(local_ffprobe):
        return local_ffprobe
    return "ffprobe"


def get_video_duration_ms(video_path: str) -> Optional[int]:
    """使用 ffprobe 获取视频总时长（毫秒）"""
    try:
        ffprobe_bin = get_ffprobe_cmd()
        cmd = [
            ffprobe_bin,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if result.returncode == 0 and result.stdout.strip():
            duration_sec = float(result.stdout.strip())
            return int(duration_sec * 1000)
    except Exception:
        pass
    return None
