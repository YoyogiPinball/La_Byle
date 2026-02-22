# -*- coding: utf-8 -*-
"""
gui.py — La_Byle メインGUI (customtkinter)
1ページ構成。ディスプレイ一覧は折りたたみ可能（デフォルト閉）。
ログエリアなし: デバッグ出力は --debug 引数でコンソールに流す。
"""

import os
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk
import config
from utils import resource_path

ICON_PATH = resource_path("labyle.ico")

SEP_COLOR = "gray30"


def _f(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def _sep(parent) -> None:
    ctk.CTkFrame(parent, height=1, fg_color=SEP_COLOR).pack(
        fill="x", padx=10, pady=(8, 4))


# ── 折りたたみセクション ────────────────────────────────────────
class _Collapsible:
    """
    タイトルボタンをクリックで内容を展開/折りたたみするコンポーネント。
    content frame はタイトルボタンと同じ outer frame 内に配置することで、
    展開時に必ずタイトルの「真下」に表示される。
    """

    def __init__(self, parent, title: str, folded: bool = True) -> None:
        self._folded = folded
        self._title  = title

        # outer に button と content を両方入れる → 展開位置が常にタイトル直下
        self._outer = ctk.CTkFrame(parent, fg_color="transparent")
        self._outer.pack(fill="x", padx=0, pady=0)

        self._btn = ctk.CTkButton(
            self._outer,
            text=self._label(),
            anchor="w",
            height=28,
            font=_f(13, "bold"),
            fg_color="transparent",
            hover_color=SEP_COLOR,
            text_color=["gray14", "gray84"],
            command=self._toggle,
        )
        self._btn.pack(fill="x", padx=0, pady=(4, 0))

        ctk.CTkFrame(self._outer, height=1, fg_color=SEP_COLOR).pack(
            fill="x", padx=4, pady=(0, 4))

        # content frame を outer 内に配置
        self.frame = ctk.CTkFrame(self._outer, fg_color="transparent")
        if not folded:
            self.frame.pack(fill="x", padx=0)

    def _label(self) -> str:
        return f"  {'▶' if self._folded else '▼'}  {self._title}"

    def _toggle(self) -> None:
        self._folded = not self._folded
        self._btn.configure(text=self._label())
        if self._folded:
            self.frame.pack_forget()
        else:
            self.frame.pack(fill="x", padx=0)


# ── メインウィンドウ ───────────────────────────────────────────
class LaByleWindow:
    def __init__(
        self,
        cfg: dict,
        on_save:      Callable,
        on_apply_now: Callable,
    ) -> None:
        self._cfg          = cfg
        self._on_save      = on_save
        self._on_apply_now = on_apply_now
        self._build_root()
        self._build_content()

    def _build_root(self) -> None:
        THEME = resource_path("assets/theme_gold.json")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme(THEME)

        self.root = ctk.CTk()
        self.root.title("La_Byle")
        self.root.geometry("540x400")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ウィンドウ端の透過を防ぐ: bg を CTk のダーク背景色に合わせる
        self.root.configure(bg="#242424")

        # タイトルバー・タスクバーアイコン
        if os.path.exists(ICON_PATH):
            try:
                self.root.iconbitmap(ICON_PATH)
            except Exception:
                pass

        # DPI に合わせたフォントスケーリング補正
        try:
            dpi = self.root.winfo_fpixels('1i')
            self.root.tk.call('tk', 'scaling', dpi / 72.0)
        except Exception:
            pass

    def _build_content(self) -> None:
        p = self.root
        self._folder_section(p)
        self._interval_section(p)
        self._monitor_section(p)   # デフォルト閉
        self._options_section(p)
        self._button_row(p)

    # ── フォルダー設定 ────────────────────────────────────────
    def _folder_section(self, p) -> None:
        self._landscape_var = ctk.StringVar(
            value=self._cfg.get("landscape_folder", ""))
        self._portrait_var  = ctk.StringVar(
            value=self._cfg.get("portrait_folder", ""))

        for label, var in [
            ("📁  縦画像フォルダー", self._portrait_var),
            ("📁  横画像フォルダー", self._landscape_var),
        ]:
            ctk.CTkLabel(p, text=label, anchor="w", font=_f(13)).pack(
                fill="x", padx=14, pady=(10, 2))
            row = ctk.CTkFrame(p, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=(0, 4))
            
            # 入力欄を横幅いっぱい（expand=True, fill="x"）に広げる
            ctk.CTkEntry(row, textvariable=var, font=_f(12)).pack(
                side="left", fill="x", expand=True, padx=(0, 6))
            
            ctk.CTkButton(
                row, text="参照", width=70, font=_f(12),
                command=lambda v=var: self._browse(v),
            ).pack(side="left")

    # ── 変更間隔 ──────────────────────────────────────────────
    def _interval_section(self, p) -> None:
        _sep(p)
        ctk.CTkLabel(p, text="変更間隔", anchor="w",
                     font=_f(13, "bold")).pack(fill="x", padx=14, pady=(0, 2))
        minutes = int(self._cfg.get("interval_minutes", 360))
        if minutes % 60 == 0:
            init_val, init_unit = str(minutes // 60), "時間"
        else:
            init_val, init_unit = str(minutes), "分"
        self._interval_var = ctk.StringVar(value=init_val)
        self._unit_var     = ctk.StringVar(value=init_unit)
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkEntry(row, textvariable=self._interval_var,
                     width=70, font=_f(13)).pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(row, values=["分", "時間"],
                          variable=self._unit_var,
                          width=90, font=_f(13)).pack(side="left")
        ctk.CTkLabel(row, text="  ごとに壁紙を変更",
                     font=_f(12), anchor="w").pack(side="left")

    # ── ディスプレイ一覧（折りたたみ・デフォルト閉） ─────────
    def _monitor_section(self, p) -> None:
        col = _Collapsible(p, "ディスプレイ一覧", folded=True)

        self._monitor_frame = ctk.CTkFrame(col.frame)
        self._monitor_frame.pack(fill="x", padx=14, pady=(0, 4))

        for ci, (txt, w) in enumerate(
            [("#", 28), ("名前", 160), ("解像度", 110), ("向き", 130)]
        ):
            ctk.CTkLabel(self._monitor_frame, text=txt, width=w, anchor="w",
                         font=_f(12, "bold")).grid(
                row=0, column=ci, padx=4, pady=3, sticky="w")

        self.refresh_monitors()

        ctk.CTkButton(
            col.frame, text="ディスプレイ情報を再取得",
            width=200, height=28, font=_f(12),
            command=self.refresh_monitors,
        ).pack(anchor="e", padx=14, pady=(2, 6))

    def refresh_monitors(self) -> None:
        from monitor import get_monitors
        frame = self._monitor_frame
        for w in frame.grid_slaves():
            if int(w.grid_info()["row"]) > 0:
                w.destroy()
        monitors = get_monitors()
        if not monitors:
            ctk.CTkLabel(frame, text="（取得失敗）", font=_f(12)).grid(
                row=1, column=0, columnspan=4, padx=4)
            return
        for mon in monitors:
            r = mon.index + 1
            for ci, (val, w) in enumerate(zip(
                [str(r), mon.name, f"{mon.width}×{mon.height}", mon.orientation],
                [28, 160, 110, 130],
            )):
                ctk.CTkLabel(frame, text=val, width=w, anchor="w",
                             font=_f(12)).grid(
                    row=r, column=ci, padx=4, pady=2, sticky="w")

    # ── オプション ────────────────────────────────────────────
    def _options_section(self, p) -> None:
        _sep(p)
        self._auto_reapply_var = ctk.BooleanVar(
            value=self._cfg.get("auto_reapply_on_orientation_change", True))
        self._auto_start_var = ctk.BooleanVar(
            value=self._cfg.get("auto_start", True))
        for text, var in [
            ("モニター向き変更時に自動で壁紙を再適用", self._auto_reapply_var),
            ("Windows起動時に自動で開始",             self._auto_start_var),
        ]:
            ctk.CTkCheckBox(p, text=text, variable=var,
                            font=_f(13)).pack(
                anchor="w", padx=18, pady=(0, 4))

    # ── ボタン行 ──────────────────────────────────────────────
    def _button_row(self, p) -> None:
        _sep(p)
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 6))
        
        # 左右のボタンがそれぞれ半分の領域（expand=True）を持ち、横幅いっぱいに広がるようにする
        ctk.CTkButton(
            row, text="▶  次へ", font=_f(13),
            command=self._apply_now, height=36
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))
        
        ctk.CTkButton(
            row, text="💾  保存", font=_f(13),
            command=self._save, height=36
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))


    # ── ロジック ─────────────────────────────────────────────
    def _browse(self, var: ctk.StringVar) -> None:
        path = filedialog.askdirectory(title="フォルダーを選択")
        if path:
            var.set(path)

    def _collect_cfg(self) -> dict:
        unit = self._unit_var.get()
        try:
            val = int(self._interval_var.get())
        except ValueError:
            val = config.DEFAULTS["interval_minutes"]
        minutes = val if unit == "分" else val * 60
        return {
            "landscape_folder": self._landscape_var.get(),
            "portrait_folder":  self._portrait_var.get(),
            "interval_minutes": minutes,
            "mode":             "random",
            "auto_reapply_on_orientation_change": self._auto_reapply_var.get(),
            "auto_start":       self._auto_start_var.get(),
        }

    def _apply_now(self) -> None:
        self._on_apply_now(self._collect_cfg())

    def _save(self) -> None:
        self._on_save(self._collect_cfg())

    def _on_close(self) -> None:
        self.hide()

    def show(self) -> None:
        self.root.after(0, self._do_show)

    def _do_show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self) -> None:
        self.root.withdraw()

    def run(self) -> None:
        self.root.mainloop()

    def destroy(self) -> None:
        self.root.after(0, self.root.destroy)
