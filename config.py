# -*- coding: utf-8 -*-
"""
config.py — 設定ファイル (config.json) の読み書き
"""

import json
import os
import sys

# 実行ファイル(.exe)か、通常のスクリプト(.py)かでパスを切り替える
if getattr(sys, 'frozen', False):
    # PyInstallerでビルドされたexeから実行されている場合、exeの場所を取得
    base_dir = os.path.dirname(sys.executable)
else:
    # 開発環境（.py）から実行されている場合
    base_dir = os.path.dirname(__file__)

CONFIG_PATH = os.path.join(base_dir, "config.json")

# ── デフォルト値 ──────────────────────────────────────────────

DEFAULTS: dict = {
    "landscape_folder": "",
    "portrait_folder":  "",
    "interval_minutes": 360,
    "mode":             "random",
    "auto_reapply_on_orientation_change": True,
    "auto_start":       True,
    "auto_change_enabled": True,
    "change_on_startup":   False,
    "schedule_mode":       "interval",   # "interval" or "time"
    "daily_time":          "09:00",      # HH:MM (schedule_mode="time" のとき使用)
    "last_executed_date":  "",           # YYYY-MM-DD (時刻指定モードのキャッチアップ判定用)
}


def load() -> dict:
    """
    config.json を読み込んで返す。
    ファイルがなければデフォルト値で新規作成する。
    キーが不足している場合もデフォルトで補完する。
    """
    if not os.path.exists(CONFIG_PATH):
        save(DEFAULTS.copy())
        return DEFAULTS.copy()

    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # 古いバージョンにキーが足りない場合に補完
        for k, v in DEFAULTS.items():
            data.setdefault(k, v)
        return data
    except (json.JSONDecodeError, OSError):
        # 破損していたらデフォルトで上書き
        save(DEFAULTS.copy())
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    """
    cfg を config.json に書き込む。
    """
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def interval_seconds(cfg: dict) -> int:
    """cfg の interval_minutes を秒に変換して返す。"""
    return int(cfg.get("interval_minutes", DEFAULTS["interval_minutes"])) * 60
