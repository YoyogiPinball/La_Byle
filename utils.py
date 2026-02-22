# -*- coding: utf-8 -*-
"""
utils.py — 共通ユーティリティ

resource_path():
  通常実行時はスクリプトの隣を基点、
  PyInstaller でビルドされた .exe では sys._MEIPASS（一時解凍フォルダ）を基点にする。
  アセットファイルのパス解決に必ず使うこと。

使い方:
  from utils import resource_path
  THEME = resource_path("assets/theme_gold.json")
  ICON  = resource_path("labyle.ico")
"""

import os
import sys


def resource_path(relative: str) -> str:
    """
    相対パスを絶対パスに変換して返す。

    - 通常実行: このファイル（utils.py）と同じディレクトリを基点とする
    - PyInstaller --onefile: sys._MEIPASS（実行時の一時解凍先）を基点とする

    .spec ファイルに以下を追加しておくこと:
      datas=[
          ("assets/theme_gold.json", "assets"),
          ("labyle.ico", "."),
      ]
    """
    try:
        base = sys._MEIPASS            # PyInstaller 実行時に存在する属性
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)
