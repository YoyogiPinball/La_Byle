# -*- coding: utf-8 -*-
"""
scheduler.py — 定間隔での壁紙変更タイマー管理

【設計】
  threading.Timer は一度きりの遅延実行のため、
  コールバック内で次の Timer を再スケジュールすることで繰り返し実行を実現する。
  stop() で停止フラグを立てて再スケジュールを止める。
  trigger_now() は現在の Timer をキャンセルして即時実行 + 再スケジュールする。
"""

import threading
import logging

logger = logging.getLogger("la_byle")


class Scheduler:
    def __init__(self) -> None:
        self._timer:    threading.Timer | None = None
        self._running:  bool = False
        self._interval: float = 0.0
        self._callback  = None
        self._lock      = threading.Lock()

    # ─────────────────────────────────────────
    def start(self, interval_sec: float, callback) -> None:
        """
        interval_sec 秒ごとに callback を呼び出す。
        既にスケジュール中なら一度 stop() してから再起動。
        """
        self.stop()
        with self._lock:
            self._interval = interval_sec
            self._callback = callback
            self._running  = True
        logger.info(f"[Scheduler] 開始: 間隔 {interval_sec:.0f}秒")
        self._schedule_next()

    def stop(self) -> None:
        """スケジューラを停止する。"""
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
        logger.info("[Scheduler] 停止")

    def trigger_now(self) -> None:
        """
        現在のタイマーをキャンセルし、即時 callback を実行した後、
        次のタイマーを再スケジュールする。
        """
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
        logger.info("[Scheduler] 即時実行")
        self._run()

    @property
    def is_running(self) -> bool:
        return self._running

    # ── 内部 ──────────────────────────────────
    def _schedule_next(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._interval, self._run)
            self._timer.daemon = True
            self._timer.start()

    def _run(self) -> None:
        """タイマー発火時の処理。callback を呼んで次をスケジュール。"""
        try:
            if self._callback:
                self._callback()
        except Exception as e:
            logger.error(f"[Scheduler] callback エラー: {e}")
        self._schedule_next()
