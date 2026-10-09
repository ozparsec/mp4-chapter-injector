# -*- coding: utf-8 -*-
"""
MP4 章节信息批量注入工具 (MP4 Chapter Injector)
功能：
1. 选择目录，自动匹配 mp4 视频文件与同名章节文本
2. 解析 OGM / 简易时间戳格式章节信息
3. 使用 FFmpeg 进行无损元数据注入 (-c copy)，保持原画质与音质
4. 完美兼容 PotPlayer / VLC 播放器交互选择章节
5. 内置测试样例一键生成（视频与章节文本）
6. 提供全功能图形界面 (GUI) 与终端命令行 (CLI) 双运行模式
"""

import os
import sys
import argparse
import subprocess
import tempfile
import threading
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass

from chapter_parser import (
    read_text_with_auto_encoding,
    parse_chapters_content,
    build_ffmetadata_content,
    get_video_duration_ms,
    ms_to_timestamp
)
from generate_samples import generate_sample_suite


def app_dir() -> str:
    """程序所在目录（兼容 PyInstaller 打包运行与源码直接运行）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(rel: str) -> str:
    """获取内置资源文件路径（兼容 PyInstaller 打包运行与源码直接运行）"""
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)


@dataclass
class VideoTask:
    video_path: str
    txt_path: Optional[str] = None
    chapters: List[Dict[str, any]] = None
    duration_ms: Optional[int] = None
    status: str = "未处理"  # "待处理", "就绪", "缺失章节文本", "处理中", "成功", "失败"
    output_path: Optional[str] = None
    error_msg: str = ""
    rel_path: str = ""  # 相对扫描根目录的相对路径

    @property
    def video_name(self) -> str:
        # 当存在多级子目录时，显示相对路径；否则显示文件名
        return self.rel_path if self.rel_path else os.path.basename(self.video_path)

    @property
    def txt_name(self) -> str:
        if not self.txt_path:
            return "未找到匹配文本"
        return os.path.basename(self.txt_path)

    @property
    def chapter_count(self) -> int:
        return len(self.chapters) if self.chapters else 0

    @property
    def duration_str(self) -> str:
        return ms_to_timestamp(self.duration_ms) if self.duration_ms is not None else "--:--:--"


class ChapterInjectorCore:
    """核心注入引擎"""

    SUPPORTED_EXTENSIONS = ('.mp4', '.m4v', '.mov')
    TXT_SUFFIXES = ('.txt', '.chapters.txt', '.chapter.txt', '.chap')

    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        self.log_callback = log_callback or (lambda msg: print(msg))

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def scan_directory(self, folder_path: str, recursive: bool = True) -> List[VideoTask]:
        """扫描目录中所有视频文件并自动匹配同名章节文本（支持单层扫描与递归子目录扫描）"""
        if not os.path.isdir(folder_path):
            self.log(f"[!] 指定的目录不存在: {folder_path}")
            return []

        tasks = []
        abs_root = os.path.abspath(folder_path)

        def _scan_folder(curr_dir: str):
            try:
                entries = os.listdir(curr_dir)
            except Exception as e:
                self.log(f"[!] 读取目录失败 {curr_dir}: {e}")
                return

            # 建立当前目录下文本文件索引（小写 -> 真实文件名）
            txt_map = {}
            for f in entries:
                name, ext = os.path.splitext(f)
                if ext.lower() == '.txt':
                    txt_map[f.lower()] = f
                    txt_map[name.lower()] = f

            for f in sorted(entries):
                _, ext = os.path.splitext(f)
                if ext.lower() in self.SUPPORTED_EXTENSIONS:
                    video_full = os.path.join(curr_dir, f)
                    if not os.path.isfile(video_full):
                        continue
                    base_name = os.path.splitext(f)[0]

                    # 寻找同目录下的匹配章节文本
                    matched_txt = None
                    for suffix in self.TXT_SUFFIXES:
                        candidate = f"{base_name}{suffix}".lower()
                        if candidate in txt_map:
                            matched_txt = os.path.join(curr_dir, txt_map[candidate])
                            break

                    rel_p = os.path.relpath(video_full, abs_root).replace('\\', '/')
                    task = VideoTask(video_path=video_full, rel_path=rel_p)

                    if matched_txt and os.path.exists(matched_txt):
                        task.txt_path = matched_txt
                        content = read_text_with_auto_encoding(matched_txt)
                        chaps = parse_chapters_content(content)
                        task.chapters = chaps
                        task.duration_ms = get_video_duration_ms(video_full)
                        if chaps:
                            task.status = "就绪"
                        else:
                            task.status = "章节文本格式无法解析"
                    else:
                        task.status = "未找到同名txt"

                    tasks.append(task)

        if not recursive:
            _scan_folder(abs_root)
        else:
            for root, dirs, files in os.walk(abs_root):
                # 默认不搜索输出目录 with_chapters（在 os.walk 中原地修改 dirs 可阻止递归进入该目录）
                dirs[:] = [d for d in dirs if d.lower() != 'with_chapters']
                # 如果当前遍历目录名称就是 with_chapters 则跳过
                if os.path.basename(root).lower() == 'with_chapters':
                    continue
                _scan_folder(root)

        return tasks

    def get_ffmpeg_cmd(self) -> str:
        """获取 ffmpeg 路径：优先程序(exe)所在目录下的 ffmpeg.exe，其次系统 PATH"""
        local_ffmpeg = os.path.join(app_dir(), "ffmpeg.exe")
        if os.path.isfile(local_ffmpeg):
            return local_ffmpeg
        return "ffmpeg"

    def inject_chapter(self, task: VideoTask, output_dir: str, overwrite: bool = False) -> bool:
        """执行单文件的章节信息注入（支持保留子目录层级结构）"""
        if not task.txt_path or not task.chapters:
            task.status = "失败: 无有效章节"
            return False

        video_name = os.path.basename(task.video_path)

        if overwrite:
            # 写入原视频目录下的临时文件，成功后再重命名覆盖原文件
            parent_dir = os.path.dirname(task.video_path)
            target_out = os.path.normpath(os.path.join(parent_dir, f".tmp_{os.getpid()}_{video_name}"))
            final_out = task.video_path
        else:
            # 非覆盖模式：保持子目录相对层级
            if task.rel_path and ('/' in task.rel_path or '\\' in task.rel_path):
                rel_dir = os.path.dirname(task.rel_path)
                curr_out_dir = os.path.normpath(os.path.join(output_dir, rel_dir))
            else:
                curr_out_dir = output_dir
            os.makedirs(curr_out_dir, exist_ok=True)
            target_out = os.path.normpath(os.path.join(curr_out_dir, video_name))
            final_out = target_out

        # 生成 FFMETADATA 内容
        meta_content = build_ffmetadata_content(task.chapters, task.duration_ms)

        # 写入临时 metadata 文件
        temp_meta_path = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.txt', delete=False) as tmp:
                tmp.write(meta_content)
                temp_meta_path = tmp.name

            # FFmpeg 无损注入命令
            ffmpeg_bin = self.get_ffmpeg_cmd()
            cmd = [
                ffmpeg_bin, '-y',
                '-i', task.video_path,
                '-i', temp_meta_path,
                '-map_metadata', '1',
                '-c', 'copy',
                '-movflags', 'use_metadata_tags',
                target_out
            ]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if proc.returncode != 0:
                task.status = "注入失败"
                task.error_msg = proc.stderr
                self.log(f"[-] 处理失败: {task.video_name}, 详情: {proc.stderr[-300:]}")
                if os.path.exists(target_out):
                    try:
                        os.remove(target_out)
                    except Exception:
                        pass
                return False

            if overwrite:
                # 备份并覆盖
                bak_path = task.video_path + ".bak"
                if os.path.exists(bak_path):
                    os.remove(bak_path)
                os.replace(task.video_path, bak_path)
                os.replace(target_out, task.video_path)
                task.output_path = task.video_path
            else:
                task.output_path = target_out

            task.status = "注入成功"
            self.log(f"[√] 章节注入成功: {task.video_name} -> {task.output_path} (共 {len(task.chapters)} 个章节)")
            return True

        except Exception as e:
            task.status = "处理异常"
            task.error_msg = str(e)
            self.log(f"[-] 异常: {task.video_name}: {e}")
            return False
        finally:
            if temp_meta_path and os.path.exists(temp_meta_path):
                try:
                    os.remove(temp_meta_path)
                except Exception:
                    pass


# =========================================================================
# GUI 图形化界面实现 (Tkinter)
# =========================================================================

def run_gui():
    # 设置高 DPI 支持 (Windows) —— 必须在创建 Tk root 之前调用才生效
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import tkinter.font as tkfont

    class ModernChapterApp:
        def __init__(self, root: tk.Tk):
            self.root = root
            self.root.title("MP4 章节信息批量注入工具 (兼容 PotPlayer / VLC)")

            # 窗体尺寸大幅拓宽与增高：宽度增加 1/4（至约 1480），高度增加 1 倍（至约 1400），兼顾屏幕自适应居中防溢出
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            win_w = min(1480, max(960, int(screen_w * 0.95)))
            win_h = min(1400, max(600, int(screen_h * 0.90)))
            pos_x = max(0, (screen_w - win_w) // 2)
            pos_y = max(10, (screen_h - win_h) // 2 - 20)
            self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
            self.root.minsize(820, 480)

            self.core = ChapterInjectorCore(log_callback=self.append_log)
            self.tasks: List[VideoTask] = []
            self.is_processing = False

            self.setup_styles()
            self.create_menu()
            self.create_widgets()

            # 默认填充当前目录并自动扫描
            current_dir = os.path.abspath(os.getcwd())
            self.path_var.set(current_dir)
            self.scan_current_dir()

        def setup_styles(self):
            style = ttk.Style()
            style.theme_use('clam')

            # 颜色规范
            self.color_primary = "#0066cc"
            self.color_bg = "#f7f9fa"
            self.color_card = "#ffffff"
            self.color_border = "#e2e8f0"

            # 恢复常态下的字体和字号：Windows 标准 9 磅无衬线系统字体
            available_fonts = tkfont.families(self.root)
            if "Microsoft YaHei UI" in available_fonts:
                self.font_family = "Microsoft YaHei UI"
            elif "Segoe UI" in available_fonts:
                self.font_family = "Segoe UI"
            else:
                self.font_family = "TkDefaultFont"

            self.font_size = 9  # Windows 桌面应用程序常态标准字号

            self.body_font = tkfont.Font(family=self.font_family, size=self.font_size)
            self.heading_font = tkfont.Font(family=self.font_family, size=self.font_size, weight='bold')
            row_height = self.body_font.metrics('linespace') + 8   # 常态行高约 24 像素，紧凑优雅

            self.root.configure(bg=self.color_bg)
            style.configure('.', font=self.body_font, background=self.color_bg)
            style.configure('Treeview', rowheight=row_height, font=self.body_font)
            style.configure('Treeview.Heading', font=self.heading_font)
            style.configure('Primary.TButton', font=self.heading_font, foreground='white', background=self.color_primary)
            style.configure('TButton', font=self.body_font)
            style.configure('TEntry', font=self.body_font)
            style.configure('TCheckbutton', font=self.body_font)
            style.map('Primary.TButton', background=[('active', '#0052a3')])

        def create_menu(self):
            """创建顶部菜单栏"""
            menubar = tk.Menu(self.root)

            # 文件菜单
            file_menu = tk.Menu(menubar, tearoff=0)
            file_menu.add_command(label="📁 浏览文件夹...", command=self.browse_folder)
            file_menu.add_command(label="🔄 重新扫描目录", command=self.scan_current_dir)
            file_menu.add_separator()
            file_menu.add_command(label="📂 打开输出目录", command=self.open_output_folder)
            file_menu.add_separator()
            file_menu.add_command(label="❌ 退出程序", command=self.root.quit)
            menubar.add_cascade(label="文件 (F)", menu=file_menu)

            # 操作菜单
            action_menu = tk.Menu(menubar, tearoff=0)
            action_menu.add_command(label="🚀 一键批量注入章节", command=self.start_batch_inject)
            action_menu.add_command(label="▶ 播放选中的视频", command=self.play_selected_video)
            action_menu.add_separator()
            action_menu.add_command(label="✨ 自动生成测试样例", command=self.generate_sample)
            menubar.add_cascade(label="操作 (A)", menu=action_menu)

            # 帮助菜单
            help_menu = tk.Menu(menubar, tearoff=0)
            help_menu.add_command(label="📖 软件使用说明 (User Guide)", command=self.show_user_manual)
            help_menu.add_command(label="💡 播放器章节跳转指南", command=self.show_player_guide)
            help_menu.add_separator()
            help_menu.add_command(label="ℹ 关于 (About)...", command=self.show_about_dialog)
            menubar.add_cascade(label="帮助 (H)", menu=help_menu)

            self.root.config(menu=menubar)

        def create_widgets(self):
            # 1. 顶部操作卡片
            top_frame = tk.Frame(self.root, bg="#ffffff", bd=1, relief="solid")
            top_frame.pack(side="top", fill="x", padx=10, pady=(8, 4))

            # 目录选择行
            dir_frame = tk.Frame(top_frame, bg="#ffffff")
            dir_frame.pack(fill="x", padx=10, pady=(8, 4))

            tk.Label(dir_frame, text="目标视频目录:", font=(self.font_family, self.font_size, 'bold'), bg="#ffffff").pack(side="left")
            self.path_var = tk.StringVar()
            dir_entry = ttk.Entry(dir_frame, textvariable=self.path_var)
            dir_entry.pack(side="left", fill="x", expand=True, padx=6)

            btn_browse = ttk.Button(dir_frame, text="浏览文件夹...", command=self.browse_folder)
            btn_browse.pack(side="left", padx=2)

            btn_scan = ttk.Button(dir_frame, text="重新扫描", command=self.scan_current_dir)
            btn_scan.pack(side="left", padx=2)

            # 功能选项工具栏行（操作按钮居左，选项复选框居右）
            btn_bar = tk.Frame(top_frame, bg="#ffffff")
            btn_bar.pack(fill="x", padx=10, pady=(4, 8))

            # 左侧核心按钮群
            left_btns = tk.Frame(btn_bar, bg="#ffffff")
            left_btns.pack(side="left")

            self.btn_inject = ttk.Button(
                left_btns, text="🚀 一键批量注入",
                style='Primary.TButton', command=self.start_batch_inject
            )
            self.btn_inject.pack(side="left", padx=(0, 4))

            btn_play = ttk.Button(
                left_btns, text="▶ 播放选中视频",
                command=self.play_selected_video
            )
            btn_play.pack(side="left", padx=2)

            btn_open_folder = ttk.Button(
                left_btns, text="📂 打开输出目录",
                command=self.open_output_folder
            )
            btn_open_folder.pack(side="left", padx=2)

            btn_sample = ttk.Button(
                left_btns, text="✨ 生成样例",
                command=self.generate_sample
            )
            btn_sample.pack(side="left", padx=2)

            btn_about = ttk.Button(
                left_btns, text="ℹ 关于",
                command=self.show_about_dialog
            )
            btn_about.pack(side="left", padx=2)

            # 右侧设置选项群（精炼文字，绝不超出视口）
            right_opts = tk.Frame(btn_bar, bg="#ffffff")
            right_opts.pack(side="right")

            self.recursive_var = tk.BooleanVar(value=True)
            chk_recursive = ttk.Checkbutton(
                right_opts, text="搜索子目录(递归)",
                variable=self.recursive_var,
                command=self.scan_current_dir
            )
            chk_recursive.pack(side="left", padx=4)

            self.overwrite_var = tk.BooleanVar(value=False)
            chk_overwrite = ttk.Checkbutton(
                right_opts, text="覆盖原视频(.bak备份)",
                variable=self.overwrite_var
            )
            chk_overwrite.pack(side="left", padx=(4, 0))

            # 2. 最底端：灰色背景系统状态栏（经典 Windows Status Bar 样式，右侧标注设计者与联系信息）
            footer_bar = tk.Frame(self.root, bg="#e2e8f0", bd=1, relief="solid")
            footer_bar.pack(side="bottom", fill="x")

            lbl_footer_right = tk.Label(
                footer_bar,
                text="Designer: Yanxin Guo  |  联系邮箱: ozparse@outlook.com",
                font=(self.font_family, self.font_size - 1),
                fg="#334155",
                bg="#e2e8f0",
                padx=10,
                pady=3
            )
            lbl_footer_right.pack(side="right")

            lbl_footer_left = tk.Label(
                footer_bar,
                text="MP4 Chapter Injector v1.2.0  |  就绪",
                font=(self.font_family, self.font_size - 1),
                fg="#64748b",
                bg="#e2e8f0",
                padx=10,
                pady=3
            )
            lbl_footer_left.pack(side="left")

            # 3. 关键布局优化：必须先 pack 底部（side="bottom"），确保状态栏、进度条与日志 100% 完整可见！
            bottom_frame = tk.Frame(self.root, bg=self.color_bg)
            bottom_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 6))

            # 统计标签与快捷提示整合行
            stat_frame = tk.Frame(bottom_frame, bg=self.color_bg)
            stat_frame.pack(fill="x", pady=(0, 3))

            self.stat_label = tk.Label(
                stat_frame,
                text="就绪",
                font=(self.font_family, self.font_size, 'bold'),
                fg="#1e293b",
                bg=self.color_bg,
                anchor="w"
            )
            self.stat_label.pack(side="left")

            tip_label = tk.Label(
                stat_frame,
                text="💡 播放提示: PotPlayer 请按快捷键 [H] 选集; VLC 在顶部菜单 [播放 -> 章节] 中切换",
                font=(self.font_family, self.font_size, 'italic'),
                fg="#64748b",
                bg=self.color_bg,
                anchor="e"
            )
            tip_label.pack(side="right")

            # 进度条
            self.progress_var = tk.DoubleVar()
            self.progress_bar = ttk.Progressbar(bottom_frame, variable=self.progress_var, maximum=100)
            self.progress_bar.pack(fill="x", pady=(0, 4))

            # 紧凑日志卡片
            log_frame = tk.Frame(bottom_frame, bg="#ffffff", bd=1, relief="solid")
            log_frame.pack(fill="x")

            self.log_text = tk.Text(log_frame, height=4, font=('Consolas', self.font_size), bg="#1e1e1e", fg="#d4d4d4")
            self.log_text.pack(side="left", fill="both", expand=True)
            log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
            self.log_text.configure(yscrollcommand=log_scroll.set)
            log_scroll.pack(side="right", fill="y")

            # 4. 中间表格视图：在顶部和底部都 pack 完毕后，最后 pack(side="top", fill="both", expand=True)
            list_frame = tk.Frame(self.root, bg="#ffffff", bd=1, relief="solid")
            list_frame.pack(side="top", fill="both", expand=True, padx=10, pady=4)

            columns = ("video", "status", "txt", "chapters", "duration", "output")
            self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
            self.tree.heading("video", text="视频文件 (相对路径 / 文件名)")
            self.tree.heading("status", text="状态")
            self.tree.heading("txt", text="匹配章节文本")
            self.tree.heading("chapters", text="章节数量")
            self.tree.heading("duration", text="视频时长")
            self.tree.heading("output", text="输出路径")

            self.tree.column("video", width=380, minwidth=180, anchor="w")
            self.tree.column("status", width=110, minwidth=80, anchor="center")
            self.tree.column("txt", width=220, minwidth=110, anchor="w")
            self.tree.column("chapters", width=90, minwidth=60, anchor="center")
            self.tree.column("duration", width=95, minwidth=70, anchor="center")
            self.tree.column("output", width=320, minwidth=120, anchor="w")

            scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=scrollbar.set)
            self.tree.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            self.tree.bind("<Double-1>", lambda event: self.play_selected_video())
            self.tree.bind("<Button-3>", self.show_context_menu)

            # 右键快捷菜单
            self.context_menu = tk.Menu(self.root, tearoff=0)
            self.context_menu.add_command(label="▶ 播放选中的视频", command=self.play_selected_video)
            self.context_menu.add_command(label="📂 打开视频所在文件夹", command=self.open_selected_folder)
            self.context_menu.add_command(label="📝 查看/编辑章节文本", command=self.open_selected_txt)
            self.context_menu.add_separator()
            self.context_menu.add_command(label="🚀 仅注入此视频", command=self.inject_single_selected)

        def append_log(self, msg: str):
            def _append():
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
            self.root.after(0, _append)

        def browse_folder(self):
            selected = filedialog.askdirectory(initialdir=self.path_var.get() or ".")
            if selected:
                self.path_var.set(os.path.abspath(selected))
                self.scan_current_dir()

        def scan_current_dir(self):
            folder = self.path_var.get().strip()
            if not folder or not os.path.exists(folder):
                return

            recursive = self.recursive_var.get()
            mode_str = "递归包含子目录" if recursive else "仅一级目录"
            self.append_log(f"[*] 正在扫描目录 ({mode_str}): {folder}")
            self.tasks = self.core.scan_directory(folder, recursive=recursive)
            self.refresh_treeview()
            ready_count = sum(1 for t in self.tasks if t.chapters)
            self.stat_label.config(
                text=f"📊 扫描完成: 共 {len(self.tasks)} 个视频 | 可注入: {ready_count} 个 | 无有效章节: {len(self.tasks) - ready_count} 个"
            )
            self.append_log(f"[+] 扫描完成: 找到 {len(self.tasks)} 个视频文件，其中 {ready_count} 个具备有效章节文本。")

        def refresh_treeview(self):
            for item in self.tree.get_children():
                self.tree.delete(item)

            for idx, task in enumerate(self.tasks):
                chap_text = f"{task.chapter_count} 个" if task.chapter_count else "-"
                out_text = os.path.basename(task.output_path) if task.output_path else "-"
                self.tree.insert(
                    "", "end", iid=str(idx),
                    values=(
                        task.video_name,
                        task.status,
                        task.txt_name,
                        chap_text,
                        task.duration_str,
                        out_text
                    )
                )

        def show_context_menu(self, event):
            row_id = self.tree.identify_row(event.y)
            if row_id:
                self.tree.selection_set(row_id)
                self.context_menu.post(event.x_root, event.y_root)

        def get_selected_task(self) -> Optional[VideoTask]:
            selected = self.tree.selection()
            if not selected:
                return None
            idx = int(selected[0])
            if 0 <= idx < len(self.tasks):
                return self.tasks[idx]
            return None

        def open_selected_folder(self):
            task = self.get_selected_task()
            if not task:
                messagebox.showinfo("提示", "请先在列表中选中一个视频。")
                return
            target_dir = os.path.dirname(task.video_path)
            if os.path.exists(target_dir):
                os.startfile(target_dir)

        def open_selected_txt(self):
            task = self.get_selected_task()
            if not task or not task.txt_path or not os.path.exists(task.txt_path):
                messagebox.showinfo("提示", "该视频暂无关联的章节文本文件。")
                return
            os.startfile(task.txt_path)

        def inject_single_selected(self):
            task = self.get_selected_task()
            if not task:
                messagebox.showinfo("提示", "请先在列表中选中一个视频。")
                return
            if not task.chapters:
                messagebox.showwarning("提示", f"该视频未找到有效章节文本，无法注入。")
                return

            folder = self.path_var.get().strip()
            overwrite = self.overwrite_var.get()
            output_dir = folder if overwrite else os.path.join(folder, "with_chapters")

            task.status = "处理中..."
            self.refresh_treeview()

            def _run():
                ok = self.core.inject_chapter(task, output_dir, overwrite)
                self.root.after(0, self.refresh_treeview)
                if ok:
                    self.root.after(0, lambda: messagebox.showinfo("成功", f"章节已成功注入至:\n{task.output_path}"))
                else:
                    self.root.after(0, lambda: messagebox.showerror("失败", f"注入失败:\n{task.error_msg}"))

            threading.Thread(target=_run, daemon=True).start()

        def generate_sample(self):
            folder = self.path_var.get().strip()
            if not folder or not os.path.exists(folder):
                messagebox.showwarning("提示", "请先选择有效的目录。")
                return

            self.append_log(f"[*] 正在当前目录下生成测试样例...")
            try:
                generate_sample_suite(folder)
                self.append_log(f"[√] 测试样例生成完毕，重新扫描目录。")
                self.scan_current_dir()
                messagebox.showinfo("样例生成成功", f"已在目录下生成测试视频与配套章节文件！\n可以直接点击【一键批量注入章节】体验效果。")
            except Exception as e:
                self.append_log(f"[-] 生成样例异常: {e}")
                messagebox.showerror("生成失败", str(e))

        def start_batch_inject(self):
            if self.is_processing:
                return

            ready_tasks = [t for t in self.tasks if t.chapters]
            if not ready_tasks:
                messagebox.showwarning("提示", "当前列表中没有找到可注入章节的视频（请确保视频同目录下存在同名 .txt 文件）")
                return

            folder = self.path_var.get().strip()
            overwrite = self.overwrite_var.get()
            output_dir = folder if overwrite else os.path.join(folder, "with_chapters")

            self.is_processing = True
            self.btn_inject.config(state="disabled")
            self.progress_var.set(0)

            threading.Thread(
                target=self._process_worker,
                args=(ready_tasks, output_dir, overwrite),
                daemon=True
            ).start()

        def _process_worker(self, tasks: List[VideoTask], output_dir: str, overwrite: bool):
            total = len(tasks)
            success_count = 0
            self.append_log(f"[*] 开始批量注入章节，共 {total} 个任务...")

            for i, task in enumerate(tasks):
                task.status = "处理中..."
                self.root.after(0, self.refresh_treeview)

                ok = self.core.inject_chapter(task, output_dir, overwrite)
                if ok:
                    success_count += 1

                progress = ((i + 1) / total) * 100
                self.root.after(0, lambda p=progress: self.progress_var.set(p))
                self.root.after(0, self.refresh_treeview)

            self.append_log(f"[√] 批处理全部完成: 成功 {success_count}/{total}。")
            self.is_processing = False
            self.root.after(0, lambda: self.btn_inject.config(state="normal"))
            self.root.after(0, lambda: self.stat_label.config(
                text=f"🎉 批量处理完毕: 成功 {success_count} / {total} | 输出目录: {output_dir}"
            ))
            self.root.after(0, lambda: messagebox.showinfo(
                "处理完成",
                f"章节注入完成！\n成功: {success_count} / {total}\n输出位置: {output_dir}"
            ))

        def play_selected_video(self):
            task = self.get_selected_task()
            if not task:
                messagebox.showinfo("提示", "请先在列表中选中一个视频。")
                return

            target_to_play = task.output_path if (task.output_path and os.path.exists(task.output_path)) else task.video_path

            if not os.path.exists(target_to_play):
                messagebox.showerror("错误", f"找不到文件: {target_to_play}")
                return

            self.append_log(f"[*] 正在调用系统默认播放器打开: {target_to_play}")
            try:
                os.startfile(target_to_play)
            except Exception as e:
                self.append_log(f"[-] 打开播放器失败: {e}")

        def open_output_folder(self):
            folder = self.path_var.get().strip()
            overwrite = self.overwrite_var.get()
            out_folder = folder if overwrite else os.path.join(folder, "with_chapters")
            if not os.path.exists(out_folder):
                out_folder = folder
            if os.path.exists(out_folder):
                os.startfile(out_folder)
            else:
                messagebox.showinfo("提示", "目录不存在。")

        def show_user_manual(self):
            """弹出软件完整使用说明窗口"""
            manual_win = tk.Toplevel(self.root)
            manual_win.title("软件使用说明 - MP4 章节信息批量注入工具")
            # 开启窗体右上角最大化、最小化与自由缩放功能；移除 transient 以便在 Windows 标题栏保留原生【最大化】与【最小化】按钮
            manual_win.resizable(True, True)

            try:
                icon_file = resource_path(os.path.join("assets", "icon.ico"))
                if os.path.isfile(icon_file):
                    manual_win.iconbitmap(icon_file)
            except Exception:
                pass

            # 宽度增加 1/3（原 860 提升至 1150），高度增加 1/2（原 640 提升至 960），兼顾屏幕保护居中
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            w = min(1150, max(860, int(screen_w * 0.90)))
            h = min(960, max(640, int(screen_h * 0.88)))

            self.root.update_idletasks()
            rx = self.root.winfo_x()
            ry = self.root.winfo_y()
            rw = self.root.winfo_width()
            rh = self.root.winfo_height()
            pos_x = max(0, rx + (rw - w) // 2)
            pos_y = max(10, ry + (rh - h) // 2)
            manual_win.geometry(f"{w}x{h}+{pos_x}+{pos_y}")
            manual_win.minsize(680, 480)
            manual_win.configure(bg="#ffffff")

            # 顶部标题栏
            top_bar = tk.Frame(manual_win, bg="#0066cc", height=54)
            top_bar.pack(fill="x")
            top_bar.pack_propagate(False)

            tk.Label(
                top_bar,
                text="📖 MP4 章节信息批量注入工具 - 软件使用说明",
                font=(self.font_family, 13, 'bold'),
                fg="#ffffff",
                bg="#0066cc"
            ).pack(anchor="w", padx=18, pady=(10, 2))

            tk.Label(
                top_bar,
                text="提示：本窗口支持自由拖拽缩放或点击右上角最大化查阅",
                font=(self.font_family, self.font_size - 1),
                fg="#e0f2fe",
                bg="#0066cc"
            ).pack(anchor="w", padx=18)

            # 读取使用说明内容
            manual_content = ""
            for candidate in [
                os.path.join(app_dir(), "使用说明.txt"),
                resource_path("使用说明.txt"),
                os.path.join(os.getcwd(), "使用说明.txt")
            ]:
                if os.path.isfile(candidate):
                    try:
                        with open(candidate, 'r', encoding='utf-8') as f:
                            manual_content = f.read()
                            break
                    except Exception:
                        pass

            if not manual_content:
                manual_content = (
                    "【图形界面操作步骤】\n"
                    "1. 选择存放视频和章节文本的目录。\n"
                    "2. 勾选【搜索子目录(递归)】深度遍历子目录（默认自动忽略 with_chapters 输出目录）。\n"
                    "3. 列表中查看视频与章节文本匹配情况，支持右键快捷操作。\n"
                    "4. 点击【🚀 一键批量注入】开始流拷贝极速无损注入。\n"
                    "5. 注入完成后，双击条目调出播放器检验效果。\n\n"
                    "【章节格式】支持标准 OGM 格式与简易时间戳格式。"
                )

            # 文本展示区域
            text_frame = tk.Frame(manual_win, bg="#ffffff", padx=14, pady=10)
            text_frame.pack(fill="both", expand=True)

            txt = tk.Text(text_frame, wrap="word", font=('Consolas', self.font_size + 1), bg="#f8fafc", fg="#1e293b", bd=1, relief="solid", padx=10, pady=8)
            txt.pack(side="left", fill="both", expand=True)
            scroll = ttk.Scrollbar(text_frame, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")

            txt.insert("1.0", manual_content)
            txt.config(state="disabled")

            # 底部关闭按钮
            bottom_bar = tk.Frame(manual_win, bg="#ffffff", pady=10)
            bottom_bar.pack(fill="x")
            btn_close = ttk.Button(bottom_bar, text="关闭说明 (Esc)", command=manual_win.destroy)
            btn_close.pack(anchor="center")
            manual_win.bind("<Escape>", lambda e: manual_win.destroy())

        def show_player_guide(self):
            """弹出主流播放器章节跳转指南"""
            guide_msg = (
                "【主流播放器章节跳转与交互指南】\n\n"
                "1. PotPlayer 播放器：\n"
                "   - 快捷键【H】：在画面中直接弹出右侧【章节/书签】抽屉栏，点击标题秒跳。\n"
                "   - 进度条断点：鼠标悬停在断点上会悬浮显示该章节标题。\n"
                "   - 上一章/下一章快捷键： [ 与 ] 键。\n\n"
                "2. VLC 播放器：\n"
                "   - 顶部菜单：点击【播放 (Playback)】->【章节 (Chapter)】直接点选。\n"
                "   - 上一章/下一章快捷键：Shift + P / Shift + N。\n\n"
                "3. IINA / 其它现代播放器：\n"
                "   - 支持侧边栏章节大纲直接点击跳转。"
            )
            messagebox.showinfo("播放器章节使用指南", guide_msg)

        def show_about_dialog(self):
            """弹出美观精致、完整无截断的关于 (About) 对话框"""
            about = tk.Toplevel(self.root)
            about.title("关于 - MP4 章节信息批量注入工具")
            # 开启自由缩放；彻底移除 transient 以便在 Windows 标题栏右上角恢复原生【最大化】与【最小化】按钮！
            about.resizable(True, True)
            about.grab_set()

            # 设置窗口左上角图标
            try:
                icon_file = resource_path(os.path.join("assets", "icon.ico"))
                if os.path.isfile(icon_file):
                    about.iconbitmap(icon_file)
            except Exception:
                pass

            # 充足舒展的窗口尺寸：宽度在原 740 基础之上再增加 1/2 (+50%) 至 1110，高 580，自适应屏幕中央居中
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            w, h = 1110, 580
            pos_x = max(0, (screen_w - w) // 2)
            pos_y = max(10, (screen_h - h) // 2 - 20)
            about.geometry(f"{w}x{h}+{pos_x}+{pos_y}")
            about.minsize(800, 480)
            about.configure(bg="#ffffff")

            # 1. 顶部标题栏背景（自适应高度，绝不裁切副标题）
            header = tk.Frame(about, bg="#0066cc", padx=24, pady=14)
            header.pack(side="top", fill="x")

            tk.Label(
                header,
                text="🎬 MP4 Chapter Injector",
                font=(self.font_family, 15, 'bold'),
                fg="#ffffff",
                bg="#0066cc"
            ).pack(anchor="w")

            tk.Label(
                header,
                text="MP4 章节信息批量注入工具  |  版本 v1.2.0 (便携通用版)",
                font=(self.font_family, self.font_size),
                fg="#e0f2fe",
                bg="#0066cc"
            ).pack(anchor="w", pady=(3, 0))

            # 2. 关键优化：【底部确定按钮】优先 pack(side="bottom") 锚定在窗体底端
            bottom_bar = tk.Frame(about, bg="#ffffff", pady=10)
            bottom_bar.pack(side="bottom", fill="x")

            btn_close = tk.Button(
                bottom_bar,
                text="确 定",
                font=(self.font_family, self.font_size, 'bold'),
                bg="#0066cc",
                fg="#ffffff",
                activebackground="#0052a3",
                activeforeground="#ffffff",
                relief="flat",
                width=16,
                pady=4,
                cursor="hand2",
                command=about.destroy
            )
            btn_close.pack(anchor="center")

            # 3. 关键优化：【设计者与联系邮箱卡片】紧接着 pack(side="bottom") 锚定在底部上方
            # 无论窗口如何缩放或拉伸，联系方式 100% 稳稳停留在眼前，绝对不会被顶出底边！
            contact_card = tk.Frame(about, bg="#f8fafc", bd=1, relief="solid", padx=16, pady=10)
            contact_card.pack(side="bottom", fill="x", padx=24, pady=(0, 6))

            # 设计者信息行
            designer_row = tk.Frame(contact_card, bg="#f8fafc")
            designer_row.pack(fill="x", pady=2)

            tk.Label(
                designer_row,
                text="设计者 (Designer):",
                font=(self.font_family, self.font_size, 'bold'),
                fg="#0f172a",
                bg="#f8fafc",
                width=18,
                anchor="w"
            ).pack(side="left")

            tk.Label(
                designer_row,
                text="Yanxin Guo",
                font=(self.font_family, self.font_size + 1, 'bold'),
                fg="#0284c7",
                bg="#f8fafc"
            ).pack(side="left")

            # 联系邮箱行
            email_row = tk.Frame(contact_card, bg="#f8fafc")
            email_row.pack(fill="x", pady=2)

            tk.Label(
                email_row,
                text="联系邮箱 (Email):",
                font=(self.font_family, self.font_size, 'bold'),
                fg="#0f172a",
                bg="#f8fafc",
                width=18,
                anchor="w"
            ).pack(side="left")

            tk.Label(
                email_row,
                text="ozparse@outlook.com",
                font=(self.font_family, self.font_size + 1),
                fg="#2563eb",
                bg="#f8fafc"
            ).pack(side="left")

            def copy_email():
                self.root.clipboard_clear()
                self.root.clipboard_append("ozparse@outlook.com")
                btn_copy.config(text="已复制 √")
                about.after(1800, lambda: btn_copy.config(text="复制邮箱"))

            btn_copy = tk.Button(
                email_row,
                text="复制邮箱",
                font=(self.font_family, self.font_size - 1),
                bg="#e2e8f0",
                fg="#0f172a",
                activebackground="#cbd5e1",
                relief="flat",
                cursor="hand2",
                padx=8,
                pady=1,
                command=copy_email
            )
            btn_copy.pack(side="left", padx=14)

            # 4. 中间内容主体：最后 pack(side="top", fill="both", expand=True) 自适应填充剩余高度
            body = tk.Frame(about, bg="#ffffff", padx=24, pady=12)
            body.pack(side="top", fill="both", expand=True)

            tk.Label(
                body,
                text="【核心功能特性】",
                font=(self.font_family, self.font_size + 1, 'bold'),
                fg="#0f172a",
                bg="#ffffff",
                anchor="w"
            ).pack(fill="x", pady=(0, 6))

            # 采用精炼单行排版，横向留白充足，纵向紧凑，绝不超高溢出
            features = [
                ("• 无损极速流拷贝：", "基于 FFmpeg -c copy 技术，无需重新编解码，秒级极速注入。"),
                ("• 多层子目录递归：", "支持全目录树深度扫描与同级文本匹配，自动排除 with_chapters 输出目录。"),
                ("• 双规范章节解析：", "完美适配 OGM 标准规范（CHAPTER01=...）与人性化简易时间戳格式。"),
                ("• 智能多编码识别：", "原生支持 UTF-8、GBK、GB18030 等中文编码，杜绝乱码。"),
                ("• 播放器友好交互：", "注入后完美支持 PotPlayer [H] 键选集、进度条断点与 VLC 章节菜单。"),
            ]

            feature_frame = tk.Frame(body, bg="#ffffff")
            feature_frame.pack(fill="both", expand=True)

            for tag, desc in features:
                item_frame = tk.Frame(feature_frame, bg="#ffffff")
                item_frame.pack(fill="x", pady=3)
                
                tk.Label(
                    item_frame,
                    text=tag,
                    font=(self.font_family, self.font_size, 'bold'),
                    fg="#1e293b",
                    bg="#ffffff",
                    anchor="w"
                ).pack(side="left")

                tk.Label(
                    item_frame,
                    text=desc,
                    font=(self.font_family, self.font_size),
                    fg="#475569",
                    bg="#ffffff",
                    anchor="w",
                    justify="left"
                ).pack(side="left", fill="x", expand=True)

            # 快捷键支持
            about.bind("<Escape>", lambda e: about.destroy())
            about.bind("<Return>", lambda e: about.destroy())

    root = tk.Tk()

    # 设置窗体左上角与任务栏图标（源码运行用 assets/icon.ico，打包后用内置资源）
    try:
        icon_file = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.isfile(icon_file):
            root.iconbitmap(icon_file)
    except Exception:
        pass

    app = ModernChapterApp(root)
    root.mainloop()


# =========================================================================
# CLI 命令行处理入口
# =========================================================================

def run_cli(args):
    target_dir = os.path.abspath(args.dir)
    mode_str = "递归扫描子目录" if args.recursive else "单层目录"
    print(f"[*] 正在扫描目录 ({mode_str}): {target_dir}")

    if args.generate_sample:
        print("[*] 正在生成测试样例视频与章节文本...")
        generate_sample_suite(target_dir)

    core = ChapterInjectorCore()
    tasks = core.scan_directory(target_dir, recursive=args.recursive)

    print(f"[+] 找到 {len(tasks)} 个视频文件:")
    ready_tasks = []
    for t in tasks:
        chap_info = f"{t.chapter_count} 个章节" if t.chapter_count else "无有效章节"
        print(f"  - {t.video_name} | {t.status} | 匹配文本: {t.txt_name} ({chap_info})")
        if t.chapters:
            ready_tasks.append(t)

    if not ready_tasks:
        print("[!] 没有找到可注入章节的视频，退出。")
        return

    output_dir = target_dir if args.overwrite else (args.output or os.path.join(target_dir, "with_chapters"))
    print(f"[*] 开始注入章节，目标输出目录: {output_dir}")

    success_count = 0
    for t in ready_tasks:
        ok = core.inject_chapter(t, output_dir=output_dir, overwrite=args.overwrite)
        if ok:
            success_count += 1

    print(f"[√] 处理完毕: 成功 {success_count}/{len(ready_tasks)}")


def main():
    parser = argparse.ArgumentParser(description="MP4 章节信息批量注入工具")
    parser.add_argument("--dir", "-d", help="目标视频目录路径")
    parser.add_argument("--output", "-o", help="输出视频目录（默认输出到 with_chapters/）")
    parser.add_argument("--overwrite", action="store_true", help="直接覆盖原视频（会自动保留 .bak 备份）")
    parser.add_argument("--recursive", "-r", action="store_true", help="递归搜索扫描子目录中的视频与章节文本")
    parser.add_argument("--generate-sample", action="store_true", help="在目标目录自动生成演示样例视频与章节文件")
    parser.add_argument("--cli", action="store_true", help="强制以命令行模式运行")

    args = parser.parse_args()

    # 如果指定了 --dir 或 --cli 或 --generate-sample，则运行 CLI 模式，否则默认启动 GUI
    if args.cli or args.dir or args.generate_sample:
        if not args.dir:
            args.dir = "."
        run_cli(args)
    else:
        run_gui()


if __name__ == '__main__':
    main()

