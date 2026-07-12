# -*- coding: utf-8 -*-
"""网易云音乐解析陈大师制作，盗卖者没有浮木 - GUI"""

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
        mb.showerror("错误", f"Unhandled exception, see:\n{LOG_FILE}\n\n{err_text[:500]}")
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
    IMPORT_ERRORS.append(f"netease_parser: {e}")
    _log_startup_error(f"IMPORT netease_parser: {e}")

try:
    from ncm_decryptor import decrypt_ncm
except Exception as e:
    IMPORT_ERRORS.append(f"ncm_decryptor: {e}")
    _log_startup_error(f"IMPORT ncm_decryptor: {e}")

try:
    from music_sources import check_source_health, get_enabled_sources
except Exception as e:
    IMPORT_ERRORS.append(f"music_sources: {e}")
    _log_startup_error(f"IMPORT music_sources: {e}")

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


class MusicToolGUI:
    QUALITY_OPTIONS = {
        "Lossless": "lossless",
        "Hi-Res": "hires",
        "ExHigh": "exhigh",
        "Higher": "higher",
        "Standard": "standard",
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("网易云音乐解析陈大师制作，盗卖者没有浮木")
        self.root.geometry("700x620")
        self.root.minsize(600, 500)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        style.theme_use("clam")

        main_frame = ttk.Frame(root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        if IMPORT_ERRORS:
            err_text = "模块加载错误：\n\n" + "\n".join(IMPORT_ERRORS) + f"\n\nSee: {LOG_FILE}"
            ttk.Label(main_frame, text=err_text, foreground="red", justify=tk.LEFT).pack(pady=40)
            self.status_var = tk.StringVar(value="模块加载失败")
            ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5).pack(fill=tk.X, side=tk.BOTTOM)
            return

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_parse = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_parse, text="　解析下载　")

        self.tab_decrypt = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_decrypt, text="　NCM解密　")

        self._build_parse_tab()
        self._build_decrypt_tab()

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5).pack(fill=tk.X, side=tk.BOTTOM)

        self._update_cookie_status()
        _log_startup_error("GUI started")

    def _on_close(self):
        _log_startup_error("GUI closed")
        self.root.destroy()

    def _build_parse_tab(self):
        # Link input
        row0 = ttk.Frame(self.tab_parse)
        row0.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row0, text="链接/ID：", width=14).pack(side=tk.LEFT)
        self.parse_link_var = tk.StringVar()
        entry = ttk.Entry(row0, textvariable=self.parse_link_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        entry.bind("<Return>", lambda e: self._on_parse_info())

        # Quality + Output
        row1 = ttk.Frame(self.tab_parse)
        row1.pack(fill=tk.X, pady=4)
        ttk.Label(row1, text="音质：", width=14).pack(side=tk.LEFT)
        self.quality_var = tk.StringVar(value="Lossless")
        ttk.Combobox(row1, textvariable=self.quality_var, values=list(self.QUALITY_OPTIONS.keys()),
                     state="readonly", width=18).pack(side=tk.LEFT)
        ttk.Label(row1, text="  Output:").pack(side=tk.LEFT)
        self.output_dir_var = tk.StringVar(value="downloads")
        ttk.Entry(row1, textvariable=self.output_dir_var, width=20).pack(side=tk.LEFT, padx=5)
        ttk.Button(row1, text="浏览", command=self._browse_output, width=7).pack(side=tk.LEFT)

        # Source status
        row_src = ttk.Frame(self.tab_parse)
        row_src.pack(fill=tk.X, pady=4)
        ttk.Label(row_src, text="音乐源：", width=14).pack(side=tk.LEFT)
        self.source_status_var = tk.StringVar(value="点击检查")
        self.source_status_label = ttk.Label(row_src, textvariable=self.source_status_var, foreground="gray")
        self.source_status_label.pack(side=tk.LEFT)
        ttk.Button(row_src, text="管理源", command=self._manage_sources, width=7).pack(side=tk.RIGHT, padx=2)
        ttk.Button(row_src, text="检查源", command=self._check_sources, width=7).pack(side=tk.RIGHT, padx=5)

        # Cookie status
        row_cookie = ttk.Frame(self.tab_parse)
        row_cookie.pack(fill=tk.X, pady=4)
        ttk.Label(row_cookie, text="网易云Cookie：", width=14).pack(side=tk.LEFT)
        self.cookie_status_var = tk.StringVar(value="未设置")
        self.cookie_status_label = ttk.Label(row_cookie, textvariable=self.cookie_status_var, foreground="gray")
        self.cookie_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row_cookie, text="设置", command=self._set_cookie, width=7).pack(side=tk.RIGHT, padx=5)

        # Buttons
        row2 = ttk.Frame(self.tab_parse)
        row2.pack(fill=tk.X, pady=10)
        ttk.Button(row2, text="查看信息", command=self._on_parse_info, width=14).pack(side=tk.LEFT)
        ttk.Button(row2, text="开始下载", command=self._on_parse_download, width=14).pack(side=tk.LEFT, padx=10)

        self.parse_progress = ttk.Progressbar(self.tab_parse, mode="indeterminate")

        # Log area
        log_frame = ttk.LabelFrame(self.tab_parse, text="输出日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.parse_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 9))
        self.parse_log.pack(fill=tk.BOTH, expand=True)

    def _browse_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir_var.set(path)

    def _log_parse(self, text: str):
        self.parse_log.configure(state=tk.NORMAL)
        self.parse_log.insert(tk.END, text + "\n")
        self.parse_log.see(tk.END)
        self.parse_log.configure(state=tk.DISABLED)

    def _on_parse_info(self):
        link = self.parse_link_var.get().strip()
        if not link:
            messagebox.showwarning("提示", "请输入链接或ID")
            return
        self._run_in_thread(self._do_parse_info, link)

    def _do_parse_info(self, link: str):
        try:
            link_type, link_id = _parse_link(link)
            quality = self.QUALITY_OPTIONS[self.quality_var.get()]
            if link_type == "playlist":
                pl = get_playlist(link)
                self._log_parse(f"\nPlaylist: {pl['name']}")
                self._log_parse(f"创建者：{pl.get('creator', 'Unknown')}")
                self._log_parse(f"歌曲数：{pl['trackCount']}")
                self._log_parse("-" * 50)
                for i, t in enumerate(pl["tracks"], 1):
                    self._log_parse(f"  {i:3d}. {t.get('artists', '?')} - {t['name']}")
            elif link_type == "album":
                al = get_album(link)
                self._log_parse(f"\n专辑：{al['name']}")
                self._log_parse(f"歌手：{al.get('artist', 'Unknown')}")
                self._log_parse(f"Tracks: {al['trackCount']}")
                self._log_parse("-" * 50)
                for i, t in enumerate(al["tracks"], 1):
                    self._log_parse(f"  {i:3d}. {t.get('artists', '?')} - {t['name']}")
            elif link_type == "song":
                info = get_song_url(link_id, level=quality, raw_input=link)
                self._log_parse(f"\n歌曲：{info.get('artist', '?')} - {info['name']}")
                self._log_parse(f"专辑：{info.get('album', '?')}")
                self._log_parse(f"音质：{info.get('level', '?')}")
                self._log_parse(f"格式：{info.get('type', '?')}")
                self._log_parse(f"大小：{info.get('size', '?')}")
            self.root.after(0, lambda: self.status_var.set(f"信息已加载：{link_id}"))
        except Exception as e:
            self._log_parse(f"【错误】{e}")
            self.root.after(0, lambda: self.status_var.set("信息加载失败"))

    def _on_parse_download(self):
        link = self.parse_link_var.get().strip()
        if not link:
            messagebox.showwarning("提示", "请输入链接或ID")
            return
        self._run_in_thread(self._do_parse_download, link)

    def _do_parse_download(self, link: str):
        try:
            link_type, link_id = _parse_link(link)
            quality = self.QUALITY_OPTIONS[self.quality_var.get()]
            output_dir = self.output_dir_var.get().strip() or "downloads"
            if link_type == "playlist":
                files = download_playlist(link, output_dir, quality)
                self._log_parse(f"已下载{len(files)}个文件")
                self.root.after(0, lambda: self.status_var.set(f"完成：{len(files)}个文件"))
            elif link_type == "album":
                files = download_album(link, output_dir, quality)
                self._log_parse(f"已下载{len(files)}个文件")
                self.root.after(0, lambda: self.status_var.set(f"完成：{len(files)}个文件"))
            elif link_type == "song":
                fp = download_song(link_id, output_dir, level=quality, raw_input=link)
                self._log_parse(f"已保存：{fp}")
                self.root.after(0, lambda: self.status_var.set("下载完成"))
        except Exception as e:
            self._log_parse(f"【错误】{e}")
            self.root.after(0, lambda: self.status_var.set("下载失败"))

    def _build_decrypt_tab(self):
        # Input
        row0 = ttk.Frame(self.tab_decrypt)
        row0.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row0, text="NCM文件/文件夹：", width=14).pack(side=tk.LEFT)
        self.decrypt_input_var = tk.StringVar()
        ttk.Entry(row0, textvariable=self.decrypt_input_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row0, text="选择文件", command=self._browse_decrypt_file, width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(row0, text="选择文件夹", command=self._browse_decrypt_folder, width=10).pack(side=tk.RIGHT)

        # Output
        row1 = ttk.Frame(self.tab_decrypt)
        row1.pack(fill=tk.X, pady=4)
        ttk.Label(row1, text="输出目录：", width=14).pack(side=tk.LEFT)
        self.decrypt_output_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.decrypt_output_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row1, text="浏览", command=self._browse_decrypt_output, width=7).pack(side=tk.RIGHT)

        # Button
        row2 = ttk.Frame(self.tab_decrypt)
        row2.pack(fill=tk.X, pady=10)
        ttk.Button(row2, text="开始解密", command=self._on_decrypt, width=14).pack(side=tk.LEFT)

        self.decrypt_progress = ttk.Progressbar(self.tab_decrypt, mode="indeterminate")

        # Log
        log_frame = ttk.LabelFrame(self.tab_decrypt, text="输出日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.decrypt_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 9))
        self.decrypt_log.pack(fill=tk.BOTH, expand=True)

    def _browse_decrypt_file(self):
        path = filedialog.askopenfilename(title="选择NCM文件", filetypes=[("NCM files", "*.ncm"), ("All files", "*.*")])
        if path:
            self.decrypt_input_var.set(path)

    def _browse_decrypt_folder(self):
        path = filedialog.askdirectory(title="选择包含NCM文件的文件夹")
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
            messagebox.showwarning("提示", "请选择NCM文件或文件夹")
            return
        self._run_in_thread(self._do_decrypt, input_path, tab=1)

    def _do_decrypt(self, input_path: str):
        try:
            output_dir = self.decrypt_output_var.get().strip() or None
            if os.path.isdir(input_path):
                ncm_files = [f for f in os.listdir(input_path) if f.lower().endswith(".ncm")]
                if not ncm_files:
                    self._log_decrypt(f"未找到.ncm文件：{input_path}")
                    self.root.after(0, lambda: self.status_var.set("未找到NCM文件"))
                    return
                self._log_decrypt(f"找到{len(ncm_files)}个NCM文件")
                out = output_dir or input_path
                success = 0
                for fname in ncm_files:
                    fp = os.path.join(input_path, fname)
                    try:
                        info = decrypt_ncm(fp, os.path.join(out, ""))
                        self._log_decrypt(f"  ✔ {fname} -> {os.path.basename(info['output_path'])} ({info['format']})")
                        success += 1
                    except Exception as e:
                        self._log_decrypt(f"  ✘ {fname}: {e}")
                self._log_decrypt(f"\n完成：{success}/{len(ncm_files)}个解密成功")
                self.root.after(0, lambda: self.status_var.set(f"Decrypt done ({success}/{len(ncm_files)})"))
            elif os.path.isfile(input_path):
                info = decrypt_ncm(input_path)
                self._log_decrypt(f"歌曲：{info['music_name']} - {info['artist']}")
                self._log_decrypt(f"格式：{info['format']}")
                self._log_decrypt(f"Output: {info['output_path']}")
                self._log_decrypt(f"大小：{info['size']:,} bytes")
                self.root.after(0, lambda: self.status_var.set("解密完成"))
            else:
                self._log_decrypt(f"【错误】路径不存在：{input_path}")
                self.root.after(0, lambda: self.status_var.set("路径无效"))
        except Exception as e:
            self._log_decrypt(f"【错误】{e}")
            self.root.after(0, lambda: self.status_var.set("解密失败"))

    def _check_sources(self):
        """Check music source availability."""
        self.source_status_var.set("检查中...")
        self.source_status_label.configure(foreground="gray")
        def do_check():
            try:
                health = check_source_health()
                enabled = get_enabled_sources()
                parts = []
                if enabled:
                    parts.append(f"{len(enabled)}个源可用")
                else:
                    parts.append("无可用源")
                online = sum(1 for s in health.values() if s.get("ok"))
                total = len(health)
                parts.append(f"({online}/{total}个URL在线)")
                status_text = " ".join(parts)
                if online > 0:
                    self.root.after(0, lambda: self.source_status_label.configure(foreground="green"))
                else:
                    self.root.after(0, lambda: self.source_status_label.configure(foreground="red"))
                self.root.after(0, lambda: self.source_status_var.set(status_text))
            except Exception as e:
                self.root.after(0, lambda: self.source_status_var.set(f"检查失败：{e}"))
                self.root.after(0, lambda: self.source_status_label.configure(foreground="red"))
        threading.Thread(target=do_check, daemon=True).start()

    def _set_cookie(self):
        """Open dialog to set NetEase cookie."""
        current = ""
        try:
            from netease_weapi import NETEASE_COOKIE
            current = NETEASE_COOKIE
        except Exception:
            pass

        dlg = tk.Toplevel(self.root)
        dlg.title("Set NetEase Cookie")
        dlg.geometry("550x280")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="请粘贴浏览器中的Cookie字符串：", font=("", 10)).pack(pady=(10, 5))
        ttk.Label(dlg, text="1. Login to https://music.163.com", foreground="gray").pack(anchor="w", padx=20)
        ttk.Label(dlg, text="2. F12 -> Application -> Cookies -> music.163.com", foreground="gray").pack(anchor="w", padx=20)
        ttk.Label(dlg, text="3. Find MUSIC_U and copy its value", foreground="gray").pack(anchor="w", padx=20)
        ttk.Label(dlg, text="4. Paste as: MUSIC_U=your_value", foreground="gray").pack(anchor="w", padx=20)

        text_frame = ttk.Frame(dlg)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        cookie_text = tk.Text(text_frame, height=3, font=("Consolas", 9))
        cookie_text.pack(fill=tk.BOTH, expand=True)
        if current:
            cookie_text.insert("1.0", current)

        def save():
            cookie_str = cookie_text.get("1.0", "end-1c").strip()
            if cookie_str:
                try:
                    from netease_weapi import set_cookie
                    set_cookie(cookie_str)
                    self._update_cookie_status()
                    dlg.destroy()
                    messagebox.showinfo("成功", "✔ Cookie已保存，VIP歌曲现可下载FLAC！")
                except Exception as e:
                    messagebox.showerror("错误", str(e))
            else:
                messagebox.showwarning("提示", "请输入Cookie")

        ttk.Button(dlg, text="保存Cookie", command=save).pack(pady=5)

    def _update_cookie_status(self):
        """Update cookie status display with VIP check."""
        try:
            from netease_weapi import has_cookie, is_vip
            if has_cookie():
                self.cookie_status_var.set("检测中...")
                self.cookie_status_label.configure(foreground="gray")
                def check():
                    vip = is_vip()
                    if vip is True:
                        self.root.after(0, lambda: self.cookie_status_var.set("✔ Cookie已设置 | VIP✔ FLAC可用"))
                        self.root.after(0, lambda: self.cookie_status_label.configure(foreground="green"))
                    elif vip is False:
                        self.root.after(0, lambda: self.cookie_status_var.set("✔ Cookie已设置 | VIP✘ 仅M4A"))
                        self.root.after(0, lambda: self.cookie_status_label.configure(foreground="orange"))
                    else:
                        self.root.after(0, lambda: self.cookie_status_var.set("✔ Cookie已设置（VIP状态未知）"))
                        self.root.after(0, lambda: self.cookie_status_label.configure(foreground="green"))
                threading.Thread(target=check, daemon=True).start()
            else:
                self.cookie_status_var.set("✘ 未设置（VIP歌曲仅M4A）")
                self.cookie_status_label.configure(foreground="gray")
        except Exception:
            self.cookie_status_var.set("未设置")

    def _manage_sources(self):
        """Open source management dialog."""
        try:
            from music_sources import (get_all_sources, toggle_source,
                                        set_preferred_source, add_custom_url,
                                        remove_custom_url, get_source_config, SOURCE_URLS)
        except Exception as e:
            messagebox.showerror("错误", str(e))
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Manage Music Sources")
        dlg.geometry("650x450")
        dlg.transient(self.root)
        dlg.grab_set()

        cols = ("Status", "Pref", "ID", "Name", "音质等级")
        tree = ttk.Treeview(dlg, columns=cols, show="headings", height=8)
        for c in cols:
            tree.heading(c, text=c)
        tree.column("Status", width=60, anchor="center")
        tree.column("Pref", width=50, anchor="center")
        tree.column("ID", width=50, anchor="center")
        tree.column("Name", width=120)
        tree.column("音质等级", width=300)
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        def refresh():
            for item in tree.get_children():
                tree.delete(item)
            for s in get_all_sources():
                st = "[ON]" if s["enabled"] else "[OFF]"
                pf = "*" if s["is_preferred"] else ""
                tree.insert("", "end", values=(st, pf, s["id"], s["name"],
                           ", ".join(s["levels"])))

        refresh()

        bf = ttk.Frame(dlg)
        bf.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(bf, text="启用/禁用", command=lambda: (
            toggle_source(tree.item(tree.selection()[0], "values")[2]) if tree.selection() else None,
            refresh(), self._check_sources()
        )).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="设为首选", command=lambda: (
            set_preferred_source(tree.item(tree.selection()[0], "values")[2]) if tree.selection() else None,
            refresh()
        )).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="刷新", command=refresh).pack(side=tk.LEFT, padx=2)

        # Custom URLs
        uf = ttk.LabelFrame(dlg, text="自定义源URL")
        uf.pack(fill=tk.X, padx=10, pady=5)

        ef = ttk.Frame(uf)
        ef.pack(fill=tk.X, padx=5, pady=5)
        url_var = tk.StringVar()
        ttk.Entry(ef, textvariable=url_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(ef, text="添加", width=6, command=lambda: (
            add_custom_url(url_var.get().strip()) if url_var.get().strip() else None,
            url_var.set(""), refresh_urls()
        )).pack(side=tk.RIGHT, padx=2)

        lb = tk.Listbox(uf, height=4)
        lb.pack(fill=tk.X, padx=5, pady=(0, 5))

        def refresh_urls():
            lb.delete(0, tk.END)
            for u in get_source_config().get("custom_urls", []):
                lb.insert(tk.END, "[C] " + u)
            for u in SOURCE_URLS:
                lb.insert(tk.END, "[B] " + u)

        ttk.Button(uf, text="删除选中", command=lambda: (
            remove_custom_url(lb.get(lb.curselection()[0])[4:]) if lb.curselection() and lb.get(lb.curselection()[0]).startswith("[C]") else None,
            refresh_urls()
        )).pack(anchor="e", padx=5, pady=(0, 5))

        refresh_urls()
        ttk.Label(dlg, text="[B]=内置  [C]=自定义  | 选中行后点击按钮操作",
                  foreground="gray").pack(pady=5)

    def _run_in_thread(self, target, *args, tab=0):
        progress = self.parse_progress if tab == 0 else self.decrypt_progress
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



def _password_gate() -> bool:
    """Show password dialog using standalone temp window.
    Returns True if correct password entered."""
    PASSWORD = "chendashiyyds"
    HINT = "私信墙后立方体获取，可以通过抖音获取"

    tmp = tk.Tk()
    tmp.withdraw()
    tmp.wm_attributes("-topmost", True)

    result = [False]

    def check():
        if pw_var.get() == PASSWORD:
            result[0] = True
            dlg.destroy()
        else:
            messagebox.showerror("口令错误", "口令不正确，请重新输入！", parent=dlg)
            pw_var.set("")
            pw_entry.focus()

    dlg = tk.Toplevel(tmp)
    dlg.title("请输入口令")
    dlg.resizable(False, False)
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    frm = ttk.Frame(dlg, padding=20)
    frm.pack()
    ttk.Label(frm, text="请输入口令以使用本工具", font=("", 12, "bold")).pack(pady=(0, 5))
    ttk.Label(frm, text=f"提示：{HINT}", foreground="gray").pack(pady=(0, 10))

    ef = ttk.Frame(frm)
    ef.pack(pady=5)
    ttk.Label(ef, text="口令：").pack(side=tk.LEFT)
    pw_var = tk.StringVar()
    pw_entry = ttk.Entry(ef, textvariable=pw_var, show="●", width=28)
    pw_entry.pack(side=tk.LEFT, padx=5)
    pw_entry.focus()

    ttk.Button(frm, text="确认", command=check, width=10).pack(pady=10)
    pw_entry.bind("<Return>", lambda e: check())

    dlg.update_idletasks()
    w = dlg.winfo_reqwidth()
    h = dlg.winfo_reqheight()
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    dlg.deiconify()
    dlg.grab_set()
    dlg.focus_force()

    tmp.wait_window(dlg)
    tmp.destroy()
    return result[0]

def main():
    if not _password_gate():
        _log_startup_error("=== GUI exited: wrong password ===")
        return

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
