# -*- coding: utf-8 -*-
"""
gui.py — La_Byle メインGUI (customtkinter)
1ページ構成。
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


# ── メインウィンドウ ───────────────────────────────────────────
class LaByleWindow:
    def __init__(
        self,
        cfg: dict,
        on_save:          Callable,
        on_apply_all:     Callable,
        on_apply_monitor: Callable,
    ) -> None:
        self._cfg              = cfg
        self._on_save          = on_save
        self._on_apply_all     = on_apply_all
        self._on_apply_monitor = on_apply_monitor
        self._build_root()
        self._build_content()

    def _build_root(self) -> None:
        THEME = resource_path("assets/theme_gold.json")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme(THEME)

        self.root = ctk.CTk()
        self.root.title("La_Byle")
        self.root.geometry("540x440")
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
        self._options_section(p)
        self._button_row(p)
        self._monitor_section(p)

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

    # ── オプション ────────────────────────────────────────────
    def _options_section(self, p) -> None:
        _sep(p)

        # 変更間隔の初期値
        minutes = int(self._cfg.get("interval_minutes", 360))
        if minutes % 1440 == 0:
            init_val, init_unit = str(minutes // 1440), "日"
        elif minutes % 60 == 0:
            init_val, init_unit = str(minutes // 60), "時間"
        else:
            init_val, init_unit = str(minutes), "分"
        self._interval_var = ctk.StringVar(value=init_val)
        self._unit_var     = ctk.StringVar(value=init_unit)

        # BooleanVars
        self._auto_change_var = ctk.BooleanVar(
            value=self._cfg.get("auto_change_enabled", True))
        self._change_on_startup_var = ctk.BooleanVar(
            value=self._cfg.get("change_on_startup", False))
        self._auto_reapply_var = ctk.BooleanVar(
            value=self._cfg.get("auto_reapply_on_orientation_change", True))
        self._auto_start_var = ctk.BooleanVar(
            value=self._cfg.get("auto_start", True))

        # 行1: 「自動変更を有効にする」チェックボックス + 変更間隔を同じ行に
        row1 = ctk.CTkFrame(p, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(0, 4))

        ctk.CTkCheckBox(row1, text="自動変更を有効にする",
                        variable=self._auto_change_var,
                        font=_f(13)).pack(side="left", padx=(4, 10))

        self._interval_entry = ctk.CTkEntry(
            row1, textvariable=self._interval_var, width=70, font=_f(13))
        self._interval_entry.pack(side="left", padx=(0, 6))

        self._unit_menu = ctk.CTkOptionMenu(
            row1, values=["分", "時間", "日"],
            variable=self._unit_var, width=90, font=_f(13))
        self._unit_menu.pack(side="left")

        ctk.CTkLabel(row1, text="  ごとに変更",
                     font=_f(12), anchor="w").pack(side="left")

        # 行2〜4: 残りのチェックボックス
        for text, var in [
            ("このソフトを起動時に壁紙を全て変更する", self._change_on_startup_var),
            ("モニター向き変更時に自動で壁紙を再適用", self._auto_reapply_var),
            ("Windows起動時に自動で開始",             self._auto_start_var),
        ]:
            ctk.CTkCheckBox(p, text=text, variable=var,
                            font=_f(13)).pack(
                anchor="w", padx=18, pady=(0, 4))

        # 「自動変更」チェック連動: 変更間隔ウィジェットの有効/無効
        self._auto_change_var.trace_add("write", self._on_auto_change_toggle)
        self._on_auto_change_toggle()  # 初期状態を反映

    def _on_auto_change_toggle(self, *_) -> None:
        state = "normal" if self._auto_change_var.get() else "disabled"
        self._interval_entry.configure(state=state)
        self._unit_menu.configure(state=state)

    # ── ボタン行 ──────────────────────────────────────────────
    def _button_row(self, p) -> None:
        _sep(p)
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 6))

        self._apply_all_btn = ctk.CTkButton(
            row, text="▶  全部変更", font=_f(13),
            command=self._apply_all, height=36
        )
        self._apply_all_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        ctk.CTkButton(
            row, text="💾  設定保存", font=_f(13),
            command=self._save, height=36
        ).pack(side="left", expand=True, fill="x")

    def set_apply_all_enabled(self, enabled: bool) -> None:
        """「全部変更」ボタンの有効/無効を切り替える（処理中ロック用）。"""
        self._apply_all_btn.configure(state="normal" if enabled else "disabled")

    def set_monitor_btn_enabled(self, enabled: bool) -> None:
        """「このモニターを変更」ボタンの有効/無効を切り替える（処理中ロック用）。"""
        self._monitor_btn.configure(state="normal" if enabled else "disabled")

    # ── モニター個別変更 ──────────────────────────────────────
    def _monitor_section(self, p) -> None:
        from monitor import get_monitors
        monitors = get_monitors()

        _sep(p)
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 8))

        if monitors:
            options = [f"モニター {m.index}  ({m.orientation})" for m in monitors]
            self._monitor_index_map = {
                f"モニター {m.index}  ({m.orientation})": m.index for m in monitors
            }
        else:
            options = ["（モニターなし）"]
            self._monitor_index_map = {}

        self._monitor_var = ctk.StringVar(value=options[0])
        ctk.CTkOptionMenu(
            row, values=options,
            variable=self._monitor_var, width=200, font=_f(13),
        ).pack(side="left", padx=(0, 8))

        self._monitor_btn = ctk.CTkButton(
            row, text="このモニターを変更", font=_f(13), height=36,
            command=self._apply_monitor,
        )
        self._monitor_btn.pack(side="left", expand=True, fill="x")

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
        if unit == "分":
            minutes = val
        elif unit == "時間":
            minutes = val * 60
        else:  # 日
            minutes = val * 1440
        return {
            "landscape_folder": self._landscape_var.get(),
            "portrait_folder":  self._portrait_var.get(),
            "interval_minutes": minutes,
            "mode":             "random",
            "auto_change_enabled": self._auto_change_var.get(),
            "change_on_startup":   self._change_on_startup_var.get(),
            "auto_reapply_on_orientation_change": self._auto_reapply_var.get(),
            "auto_start":       self._auto_start_var.get(),
        }

    def _apply_all(self) -> None:
        self.set_apply_all_enabled(False)
        self._on_apply_all(self._collect_cfg())

    def _apply_monitor(self) -> None:
        idx = self._monitor_index_map.get(self._monitor_var.get())
        if idx is None:
            return
        self.set_monitor_btn_enabled(False)
        self._on_apply_monitor(self._collect_cfg(), idx)

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
