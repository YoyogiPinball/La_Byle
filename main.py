# -*- coding: utf-8 -*-
"""
main.py — La_Byle エントリーポイント
各モジュールを組み合わせてアプリを起動する。
"""

# ── Per-Monitor DPI 対応（フォント・ボタンのジャギ解消）—他のどんな import より前に呼ぶこと ──
import ctypes as _ctypes
try:
    _ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware v1
except Exception:
    try:
        _ctypes.windll.user32.SetProcessDPIAware()       # フォールバック
    except Exception:
        pass

# タスクバーアイコンを正しく表示するためのアプリ ID 設定
# SetCurrentProcessExplicitAppUserModelID を呼ぶことで
# Windows がこのプロセスを独立したアプリとして認識し、labyle.ico がタスクバーに反映される
try:
    _ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "YoyogiPinball.LaByle"
    )
except Exception:
    pass

import logging
import os
import sys

# ── 多重起動防止（named Mutex） ────────────────────────────────
# 2重目の起動は何もせずサイレントに終了する。
# CreateMutexW はプロセスが終了すると OS が自動解放するため、
# 正常終了・強制終了どちらでも次回起動時にロックが残らない。
_MUTEX_NAME = "Local\\La_Byle_SingleInstance"
_mutex_handle = None


def _acquire_mutex() -> bool:
    """Mutex を取得して True を返す。既に起動中なら False を返す。"""
    global _mutex_handle
    _mutex_handle = _ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    last_error = _ctypes.windll.kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    return last_error != ERROR_ALREADY_EXISTS

# ── ロガー初期化 ──────────────────────────────────────────
# --debug 引数がある場合のみコンソールにログを流す。
# それ以外は NullHandler（完全無音）。ファイルへの書き出しは行わない。

_DEBUG_MODE = "--debug" in sys.argv


def _setup_logger() -> logging.Logger:
    log = logging.getLogger("la_byle")
    if log.handlers:
        return log   # 二重初期化を防ぐ

    if _DEBUG_MODE:
        log.setLevel(logging.DEBUG)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(ch)
    else:
        log.addHandler(logging.NullHandler())

    return log


logger = _setup_logger()

# ── 各モジュールをインポート ────────────────────────────────
import config
import startup
from utils import resource_path
from wallpaper import WallpaperWorker
from scheduler import Scheduler
from watcher import OrientationWatcher
from tray import TrayIcon
from gui import LaByleWindow

# ── アイコン ────────────────────────────────────────────
ICON_PATH = resource_path("labyle.ico")


def _ensure_icon() -> None:
    """
    labyle.ico が存在しない場合のみフォールバックの白アイコンを生成する。
    ユーザーが labyle.ico を用意している場合はそのまま使う。
    """
    if not os.path.exists(ICON_PATH):
        from PIL import Image
        img = Image.new("RGB", (64, 64), color=(255, 255, 255))
        img.save(ICON_PATH, format="ICO", sizes=[(64, 64)])
        logger.info(f"フォールバックアイコンを生成: {ICON_PATH}")


# ── アプリコントローラ ────────────────────────────────────────
class AppController:
    """
    GUI / Scheduler / Watcher / Tray を束ねるコントローラ。
    GUI からのコールバックをここで受け取り、各モジュールに委譲する。
    """

    def __init__(self) -> None:
        self._cfg       = config.load()
        self._scheduler = Scheduler()
        self._worker    = WallpaperWorker()
        self._watcher   = OrientationWatcher(on_change=self._on_orientation_change)
        self._window:   LaByleWindow | None = None
        self._tray:     TrayIcon     | None = None

    # ── 起動 ─────────────────────────────────────────────────

    def run(self) -> None:
        _ensure_icon()

        logger.info("=" * 50)
        logger.info("La_Byle 起動")
        logger.info(f"横フォルダ: {self._cfg['landscape_folder']}")
        logger.info(f"縦フォルダ: {self._cfg['portrait_folder']}")

        # 壁紙ワーカー（COM 専用スレッド）
        self._worker.start()

        # GUI 生成
        self._window = LaByleWindow(
            cfg          = self._cfg,
            on_save      = self._on_save,
            on_apply_now = self._on_apply_now,
        )

        # トレイ
        self._tray = TrayIcon(
            icon_path = ICON_PATH,
            on_show   = self._window.show,
            on_quit   = self._shutdown,
        )
        self._tray.start()

        # スケジューラ
        self._start_scheduler()

        # 向き変化監視
        if self._cfg.get("auto_reapply_on_orientation_change"):
            self._watcher.start()

        # mainloop (ブロッキング)
        self._window.run()

        logger.info("La_Byle 終了")

    def _start_scheduler(self) -> None:
        interval = config.interval_seconds(self._cfg)
        self._scheduler.start(interval, self._apply_wallpaper)
        logger.info(f"スケジューラ: {interval}秒間隔")

    # ── コールバック ─────────────────────────────────────────

    def _on_save(self, cfg: dict) -> None:
        """GUI「保存」→ 設定を永続化・スケジューラ再起動・スタートアップ登録を更新。"""
        self._cfg = cfg
        config.save(cfg)
        logger.info("[Controller] 設定を保存")

        # 画像キャッシュをクリア（フォルダーが変更された可能性があるため）
        self._worker.invalidate_cache()

        # スタートアップ登録/解除
        try:
            if cfg.get("auto_start"):
                startup.register()
            else:
                startup.unregister()
        except RuntimeError as e:
            logger.warning(f"[Controller] スタートアップ操作スキップ: {e}")

        # スケジューラ再起動
        self._scheduler.stop()
        self._start_scheduler()

        # 向き変化監視の ON/OFF 切り替え
        if cfg.get("auto_reapply_on_orientation_change"):
            self._watcher.start()
        else:
            self._watcher.stop()

    def _on_apply_now(self, cfg: dict) -> None:
        """
        GUI「今すぐ適用」→ UIの現在値（cfg）で即時壁紙変更。
        保存は行わず、フォルダ内容は毎回必ず再読み込みする。
        """
        # 手動変更時は常に最新のフォルダ内容を反映させるため、キャッシュを破棄
        self._worker.invalidate_cache()
        self._apply_wallpaper(cfg=cfg)

    def _on_orientation_change(self) -> None:
        """watcher から向き変化通知 → 即時壁紙変更。"""
        logger.info("[Controller] 向き変化 → 壁紙再適用")
        self._apply_wallpaper()

    # ── 壁紙適用 ─────────────────────────────────────────────

    def _apply_wallpaper(self, cfg: dict = None) -> None:
        """壁紙ワーカーにリクエストを投入する。実際の適用は COM 専用スレッドで行われる。"""
        c    = cfg or self._cfg
        land = c.get("landscape_folder", "")
        port = c.get("portrait_folder",  "")
        self._worker.submit_apply(land, port, callback=self._log_results)

    def _log_results(self, results: dict) -> None:
        """壁紙適用結果をログに出力する（Worker スレッドから呼ばれる）。"""
        for dev, path in results.items():
            if path.startswith("[SKIP]"):
                logger.info(f"  SKIP {dev}: {path}")
            elif path.startswith("["):
                logger.warning(f"  {dev} → {path}")
            else:
                short = os.path.basename(path)
                logger.info(f"  {dev} → {short}")

    # ── シャットダウン ────────────────────────────────────────

    def _shutdown(self) -> None:
        """トレイ「終了」→ 全モジュールを停止してウィンドウを破棄。"""
        logger.info("[Controller] シャットダウン")
        self._scheduler.stop()
        self._watcher.stop()
        self._worker.shutdown()
        if self._tray:
            self._tray.stop()
        if self._window:
            self._window.destroy()


# ── エントリーポイント ────────────────────────────────────────
if __name__ == "__main__":
    if not _acquire_mutex():
        # すでに起動中 → 何もせず終了（サイレント）
        sys.exit(0)
    AppController().run()
