# -*- coding: utf-8 -*-
"""网易云音乐工具箱大师制作，盗卖者全家死光 - 图形界面"""

import os
import sys
import traceback
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "error.log")

def _log_startup_error(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now()}] {msg}\n")
    except Exception:
        pass

def _global_exception_handler(exc_type, exc_value, exc_tb):
    err_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _log_startup_error(f"UNHANDLED EXCEPTION:\n{err_text}")
    try:
        import tkinter.messagebox as mb
        mb.showerror("程序错误", f"发生未捕获的异常，详情见:\n{LOG_FILE}\n\n{err_text[:500]}")
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _global_exception_handler

if HERE not in sys.path:
    sys.path.insert(0, HERE)

IMPORT_ERRORS = []

try:
    from netease_parser import (
        _parse_link, get_playlist, get_album, get_song_url,
        download_playlist, download_album, download_song,
    )
except Exception as e:
    IMPORT_ERRORS.append(f"netease_parser 加载失败: {e}")
    _log_startup_error(f"IMPORT netease_parser: {e}")

try:
    from ncm_decryptor import decrypt_ncm
except Exception as e:
    IMPORT_ERRORS.append(f"ncm_decryptor 加载失败: {e}")
    _log_startup_error(f"IMPORT ncm_decryptor: {e}")

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


class MusicToolGUI:
    QUALITY_OPTIONS = {
        "无损 (lossless)": "lossless",
        "超清母带 (hires)": "hires",
        "极高 (exhigh)": "exhigh",
        "较高 (higher)": "higher",
        "标准 (standard)": "standard",
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("网易云音乐工具箱大师制作，盗卖者全家死光")
        self.root.geometry("700x600")
        self.root.minsize(600, 500)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        style.theme_use("clam")

        main_frame = ttk.Frame(root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        if IMPORT_ERRORS:
            err_lines = ["模块加载失败，请检查文件是否完整：", ""]
            err_lines.extend(IMPORT_ERRORS)
            err_lines.append("")
            err_lines.append(f"详情见: {LOG_FILE}")
            err_label = ttk.Label(main_frame, text="\n".join(err_lines),
                                  foreground="red", font=("", 11), justify=tk.LEFT)
            err_label.pack(pady=40)
            self.status_var = tk.StringVar(value="模块加载失败")
            status_bar = ttk.Label(root, textvariable=self.status_var,
                                   relief=tk.SUNKEN, anchor=tk.W, padding=5)
            status_bar.pack(fill=tk.X, side=tk.BOTTOM)
            _log_startup_error(f"IMPORT_ERRORS: {IMPORT_ERRORS}")
            return

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_parse = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_parse, text=" 解析下载 ")

        self.tab_decrypt = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_decrypt, text=" NCM解密 ")

        self._build_parse_tab()
        self._build_decrypt_tab()

        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(root, textvariable=self.status_var,
                               relief=tk.SUNKEN, anchor=tk.W, padding=5)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        _log_startup_error("GUI started successfully")

    def _on_close(self):
        _log_startup_error("GUI closed by user")
        self.root.destroy()

    def _build_parse_tab(self):
        row0 = ttk.Frame(self.tab_parse)
        row0.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row0, text="网易云链接/ID：", width=14).pack(side=tk.LEFT)
        self.parse_link_var = tk.StringVar()
        entry = ttk.Entry(row0, textvariable=self.parse_link_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        entry.bind("<Return>", lambda e: self._on_parse_info())

        row1 = ttk.Frame(self.tab_parse)
        row1.pack(fill=tk.X, pady=4)
        ttk.Label(row1, text="音质等级：", width=14).pack(side=tk.LEFT)
        self.quality_var = tk.StringVar(value="无损 (lossless)")
        ttk.Combobox(row1, textvariable=self.quality_var,
                     values=list(self.QUALITY_OPTIONS.keys()),
                     state="readonly", width=18).pack(side=tk.LEFT)
        ttk.Label(row1, text="  输出目录：").pack(side=tk.LEFT, padx=(20, 0))
        self.parse_output_var = tk.StringVar(value=os.path.join(HERE, "downloads"))
        ttk.Entry(row1, textvariable=self.parse_output_var, width=25).pack(side=tk.LEFT, padx=5)
        ttk.Button(row1, text="浏览...", command=self._browse_parse_output, width=6).pack(side=tk.LEFT)

        row2 = ttk.Frame(self.tab_parse)
        row2.pack(fill=tk.X, pady=10)
        ttk.Button(row2, text="查看信息", command=self._on_parse_info, width=14).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row2, text="开始下载", command=self._on_parse_download, width=14).pack(side=tk.LEFT)

        self.parse_progress = ttk.Progressbar(self.tab_parse, mode="indeterminate")

        log_frame = ttk.LabelFrame(self.tab_parse, text="输出日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.parse_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 9))
        self.parse_log.pack(fill=tk.BOTH, expand=True)

    def _browse_parse_output(self):
        path = filedialog.askdirectory(title="选择下载目录", initialdir=self.parse_output_var.get())
        if path:
            self.parse_output_var.set(path)

    def _log_parse(self, text: str):
        self.parse_log.configure(state=tk.NORMAL)
        self.parse_log.insert(tk.END, text + "\n")
        self.parse_log.see(tk.END)
        self.parse_log.configure(state=tk.DISABLED)

    def _on_parse_info(self):
        link = self.parse_link_var.get().strip()
        if not link:
            messagebox.showwarning("提示", "请输入网易云音乐链接或歌曲ID")
            return
        self._run_in_thread(self._do_parse_info, link, tab=0)

    def _on_parse_download(self):
        link = self.parse_link_var.get().strip()
        if not link:
            messagebox.showwarning("提示", "请输入网易云音乐链接或歌曲ID")
            return
        self._run_in_thread(self._do_parse_download, link, tab=0)

    def _do_parse_info(self, link: str):
        try:
            link_type, _ = _parse_link(link)
            self._log_parse(f"[信息] 链接类型: {link_type}")
            if link_type == "playlist":
                pl = get_playlist(link)
                self._log_parse(f"歌单名: {pl['name']}")
                self._log_parse(f"创建者: {pl.get('creator', '未知')}")
                self._log_parse(f"歌曲数: {pl['trackCount']}")
                self._log_parse("-" * 45)
                for i, t in enumerate(pl["tracks"], 1):
                    self._log_parse(f"  {i:3d}. {t.get('artists', '?')} - {t['name']}")
            elif link_type == "album":
                al = get_album(link)
                self._log_parse(f"专辑名: {al['name']}")
                self._log_parse(f"歌手: {al.get('artist', '未知')}")
                self._log_parse(f"歌曲数: {al['trackCount']}")
                self._log_parse("-" * 45)
                for i, t in enumerate(al["tracks"], 1):
                    self._log_parse(f"  {i:3d}. {t.get('artists', '?')} - {t['name']}")
            elif link_type == "song":
                song_id = _parse_link(link)[1]
                info = get_song_url(song_id, raw_input=link)
                self._log_parse(f"歌曲: {info.get('artist', '?')} - {info['name']}")
                self._log_parse(f"专辑: {info.get('album', '?')}")
                self._log_parse(f"音质: {info.get('level', '?')}")
                self._log_parse(f"格式: {info.get('type', '?')}")
                self._log_parse(f"大小: {info.get('size', '?')}")
            self.root.after(0, lambda: self.status_var.set("信息获取完成"))
        except Exception as e:
            self._log_parse(f"[错误] {e}")
            self.root.after(0, lambda: self.status_var.set("获取失败"))

    def _do_parse_download(self, link: str):
        try:
            quality_key = self.QUALITY_OPTIONS[self.quality_var.get()]
            output_dir = self.parse_output_var.get()
            os.makedirs(output_dir, exist_ok=True)
            link_type, _ = _parse_link(link)
            self._log_parse(f"[下载] 类型: {link_type}  音质: {quality_key}  目录: {output_dir}")
            if link_type == "playlist":
                download_playlist(link, output_dir, quality_key)
            elif link_type == "album":
                download_album(link, output_dir, quality_key)
            elif link_type == "song":
                song_id = _parse_link(link)[1]
                fp = download_song(song_id, output_dir, level=quality_key, raw_input=link)
                self._log_parse(f"已保存: {fp}")
            self.root.after(0, lambda: self.status_var.set("下载完成"))
        except Exception as e:
            self._log_parse(f"[错误] {e}")
            self.root.after(0, lambda: self.status_var.set("下载失败"))

    def _build_decrypt_tab(self):
        row0 = ttk.Frame(self.tab_decrypt)
        row0.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row0, text="输入文件/文件夹：", width=15).pack(side=tk.LEFT)
        self.decrypt_input_var = tk.StringVar()
        ttk.Entry(row0, textvariable=self.decrypt_input_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        btn_frame = ttk.Frame(row0)
        btn_frame.pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="选文件", command=self._browse_decrypt_file, width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="选文件夹", command=self._browse_decrypt_folder, width=8).pack(side=tk.LEFT)

        ttk.Label(self.tab_decrypt, text="提示：选择 .ncm 文件或包含 .ncm 的文件夹",
                  foreground="gray").pack(fill=tk.X, pady=(0, 4))

        row1 = ttk.Frame(self.tab_decrypt)
        row1.pack(fill=tk.X, pady=4)
        ttk.Label(row1, text="输出目录（可选）：", width=15).pack(side=tk.LEFT)
        self.decrypt_output_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.decrypt_output_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row1, text="浏览...", command=self._browse_decrypt_output, width=6).pack(side=tk.LEFT)

        row2 = ttk.Frame(self.tab_decrypt)
        row2.pack(fill=tk.X, pady=10)
        ttk.Button(row2, text="开始解密", command=self._on_decrypt, width=14).pack(side=tk.LEFT)

        self.decrypt_progress = ttk.Progressbar(self.tab_decrypt, mode="indeterminate")

        log_frame = ttk.LabelFrame(self.tab_decrypt, text="输出日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.decrypt_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 9))
        self.decrypt_log.pack(fill=tk.BOTH, expand=True)

    def _browse_decrypt_file(self):
        path = filedialog.askopenfilename(
            title="选择 NCM 文件", filetypes=[("NCM 文件", "*.ncm"), ("所有文件", "*.*")]
        )
        if path:
            self.decrypt_input_var.set(path)

    def _browse_decrypt_folder(self):
        path = filedialog.askdirectory(title="选择包含 NCM 文件的文件夹")
        if path:
            self.decrypt_input_var.set(path)

    def _browse_decrypt_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.decrypt_output_var.set(path)

    def _log_decrypt(self, text: str):
        self.decrypt_log.configure(state=tk.NORMAL)
        self.decrypt_log.insert(tk.END, text + "\n")
        self.decrypt_log.see(tk.END)
        self.decrypt_log.configure(state=tk.DISABLED)

    def _on_decrypt(self):
        input_path = self.decrypt_input_var.get().strip()
        if not input_path:
            messagebox.showwarning("提示", "请选择 NCM 文件或包含 NCM 文件的文件夹")
            return
        self._run_in_thread(self._do_decrypt, input_path, tab=1)

    def _do_decrypt(self, input_path: str):
        try:
            output_dir = self.decrypt_output_var.get().strip() or None
            if os.path.isdir(input_path):
                ncm_files = [f for f in os.listdir(input_path) if f.lower().endswith(".ncm")]
                if not ncm_files:
                    self._log_decrypt(f"[提示] 文件夹中未找到 .ncm 文件: {input_path}")
                    self.root.after(0, lambda: self.status_var.set("未找到NCM文件"))
                    return
                self._log_decrypt(f"找到 {len(ncm_files)} 个 NCM 文件")
                out = output_dir or input_path
                success = 0
                for fname in ncm_files:
                    fp = os.path.join(input_path, fname)
                    try:
                        info = decrypt_ncm(fp, os.path.join(out, ""))
                        self._log_decrypt(f"  OK  {fname} -> {os.path.basename(info['output_path'])} ({info['format']})")
                        success += 1
                    except Exception as e:
                        self._log_decrypt(f"  FAIL {fname}: {e}")
                self._log_decrypt(f"\n完成: {success}/{len(ncm_files)} 个文件解密成功")
                self.root.after(0, lambda: self.status_var.set(f"解密完成 ({success}/{len(ncm_files)})"))
            elif os.path.isfile(input_path):
                info = decrypt_ncm(input_path)
                self._log_decrypt(f"歌曲: {info['music_name']} - {info['artist']}")
                self._log_decrypt(f"格式: {info['format']}")
                self._log_decrypt(f"输出: {info['output_path']}")
                self._log_decrypt(f"大小: {info['size']:,} 字节")
                self.root.after(0, lambda: self.status_var.set("解密完成"))
            else:
                self._log_decrypt(f"[错误] 路径不存在: {input_path}")
                self.root.after(0, lambda: self.status_var.set("路径无效"))
        except Exception as e:
            self._log_decrypt(f"[错误] {e}")
            self.root.after(0, lambda: self.status_var.set("解密失败"))

    def _run_in_thread(self, target, *args, tab=0):
        if tab == 0:
            progress = self.parse_progress
        else:
            progress = self.decrypt_progress
        progress.pack(fill=tk.X, pady=(5, 0))
        progress.start(10)
        self.status_var.set("处理中...")

        def wrapper():
            try:
                target(*args)
            except Exception as e:
                _log_startup_error(f"Thread error: {traceback.format_exc()}")
                self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
            finally:
                self.root.after(0, progress.stop)
                self.root.after(0, lambda: progress.pack_forget())

        threading.Thread(target=wrapper, daemon=True).start()


def main():
    _log_startup_error("=== GUI starting ===")
    root = tk.Tk()
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    MusicToolGUI(root)
    root.mainloop()
    _log_startup_error("=== GUI exited ===")


if __name__ == "__main__":
    main()