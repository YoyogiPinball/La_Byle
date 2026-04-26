# -*- coding: utf-8 -*-
"""
scheduler.py — 壁紙変更タイマー管理（間隔モード / 時刻指定モード）

【設計】
  threading.Timer は一度きりの遅延実行のため、
  コールバック内で次の Timer を再スケジュールすることで繰り返し実行を実現する。

  ● 間隔モード (start)
      指定秒数ごとに callback を発火。

  ● 時刻指定モード (start_time_mode)
      60 秒ごとにポーリングし、現在時刻が HH:MM を過ぎていて
      かつ「最終実行日 != 今日」なら callback を発火する。
      初回チェックは +60 秒後（起動・スリープ復帰直後の即時実行を回避）。

  stop() / is_running は両モード共通。
"""

import threading
import datetime
import logging

logger = logging.getLogger("la_byle")

POLL_INTERVAL_SEC = 60   # 時刻指定モードのポーリング周期（兼: 起動/復帰時の遅延）


class Scheduler:
    def __init__(self) -> None:
        self._timer:    threading.Timer | None = None
        self._running:  bool = False
        self._interval: float = 0.0
        self._callback  = None
        self._lock      = threading.Lock()
        # 時刻指定モード用
        self._daily_time_hhmm: str = ""
        self._last_executed_date_getter = None
        self._on_executed = None

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

    # ── 時刻指定モード ────────────────────────
    def start_time_mode(
        self,
        daily_time_hhmm: str,
        last_executed_date_getter,
        on_executed,
        callback,
    ) -> None:
        """
        毎日 HH:MM に callback を実行する。
        既にスケジュール中なら一度 stop() してから再起動。

        引数:
            daily_time_hhmm:           "HH:MM" 形式の発火時刻
            last_executed_date_getter: () -> str ("YYYY-MM-DD" or "")
                                       config から最新の最終実行日を取得する関数
            on_executed:               (today_str: str) -> None
                                       発火後に呼ばれる。設定保存を main 側に依頼するため
            callback:                  () -> None  実際の壁紙変更処理
        """
        self.stop()
        with self._lock:
            self._daily_time_hhmm = daily_time_hhmm
            self._last_executed_date_getter = last_executed_date_getter
            self._on_executed = on_executed
            self._callback = callback
            self._running = True
        logger.info(f"[Scheduler] 時刻指定モード開始: 毎日 {daily_time_hhmm}")
        self._schedule_time_check()

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

    def _schedule_time_check(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(POLL_INTERVAL_SEC, self._time_check)
            self._timer.daemon = True
            self._timer.start()

    def _time_check(self) -> None:
        """
        ポーリングごとの判定。
        指定時刻を過ぎていて、かつ今日まだ実行していなければ callback を発火する。
        """
        try:
            now = datetime.datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            last_exec = ""
            if self._last_executed_date_getter:
                last_exec = self._last_executed_date_getter() or ""

            hh, mm = map(int, self._daily_time_hhmm.split(":"))
            scheduled_today = now.replace(
                hour=hh, minute=mm, second=0, microsecond=0)

            if now >= scheduled_today and last_exec != today_str:
                logger.info(
                    f"[Scheduler] 時刻指定発火: 指定 {self._daily_time_hhmm} "
                    f"/ 現在 {now.strftime('%H:%M')} / 前回 {last_exec or '未実行'}"
                )
                if self._callback:
                    self._callback()
                if self._on_executed:
                    self._on_executed(today_str)
        except Exception as e:
            logger.error(f"[Scheduler] time_check エラー: {e}")
        self._schedule_time_check()
