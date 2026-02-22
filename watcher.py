# -*- coding: utf-8 -*-
"""
watcher.py — モニター向き変更の検知

定期的に screeninfo でモニター情報を取得し、
向き（縦/横）が変化していたら callback を呼ぶ。
"""

import threading
import logging
from typing import Callable

from monitor import get_monitors, MonitorInfo, orientations_changed

logger = logging.getLogger("la_byle")

_POLL_INTERVAL = 5.0   # 秒（ポーリング間隔）


class OrientationWatcher:
    def __init__(self, on_change: Callable) -> None:
        """
        on_change: 向き変化検知時に呼ばれるコールバック (引数なし)
        """
        self._on_change = on_change
        self._thread:   threading.Thread | None = None
        self._stop_evt: threading.Event         = threading.Event()
        self._prev:     list[MonitorInfo]       = []

    def start(self) -> None:
        """バックグラウンドスレッドでポーリングを開始する。
        既に実行中の場合は何もしない（二重起動防止）。
        """
        if self._thread is not None and self._thread.is_alive():
            logger.debug("[Watcher] 既に実行中のため start() をスキップ")
            return
        self._stop_evt.clear()
        self._prev = get_monitors()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("[Watcher] 開始")

    def stop(self) -> None:
        """ポーリングを停止する。"""
        self._stop_evt.set()
        logger.info("[Watcher] 停止")

    # ── 内部 ────────────────────────────────────────────────
    def _loop(self) -> None:
        while not self._stop_evt.wait(timeout=_POLL_INTERVAL):
            try:
                curr = get_monitors()
                if orientations_changed(self._prev, curr):
                    logger.info("[Watcher] モニター向き変化を検知")
                    self._prev = curr
                    try:
                        self._on_change()
                    except Exception as e:
                        logger.error(f"[Watcher] callback エラー: {e}")
                else:
                    self._prev = curr
            except Exception as e:
                logger.error(f"[Watcher] ポーリングエラー: {e}")
