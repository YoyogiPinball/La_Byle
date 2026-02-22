# -*- coding: utf-8 -*-
"""
tray.py — タスクトレイ常駐 (pystray ラッパー)

【設計】
  pystray の Icon.run() はブロッキングのため、
  呼び出し元は必ずデーモンスレッドで run() を起動すること。
"""

import threading
import logging
from typing import Callable

import pystray
from PIL import Image

logger = logging.getLogger("la_byle")


class TrayIcon:
    def __init__(
        self,
        icon_path: str,
        on_show:   Callable,
        on_quit:   Callable,
    ) -> None:
        """
        icon_path : ICO ファイルのパス
        on_show   : 「設定を開く」選択時のコールバック
        on_quit   : 「終了」選択時のコールバック
        """
        self._icon_path = icon_path
        self._on_show   = on_show
        self._on_quit   = on_quit
        self._icon: pystray.Icon | None = None

    def start(self) -> None:
        """デーモンスレッドでトレイアイコンを起動する。"""
        img  = Image.open(self._icon_path)
        menu = pystray.Menu(
            pystray.MenuItem("設定を開く", self._show, default=True),
            pystray.MenuItem("終了",       self._quit),
        )
        self._icon = pystray.Icon(
            name  = "La_Byle",
            icon  = img,
            title = "La_Byle",
            menu  = menu,
        )
        t = threading.Thread(target=self._icon.run, daemon=True)
        t.start()
        logger.info("[Tray] タスクトレイ起動")

    def stop(self) -> None:
        """アイコンを停止する（アプリ終了時に呼ぶ）。"""
        if self._icon:
            self._icon.stop()
            logger.info("[Tray] タスクトレイ停止")

    # ── コールバック ─────────────────────────────────────────
    def _show(self, icon=None, item=None) -> None:
        logger.info("[Tray] 設定を開く")
        self._on_show()

    def _quit(self, icon=None, item=None) -> None:
        logger.info("[Tray] 終了要求")
        self._on_quit()
