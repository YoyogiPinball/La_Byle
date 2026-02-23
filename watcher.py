# -*- coding: utf-8 -*-
"""
watcher.py — モニター向き変更の検知（WM_DISPLAYCHANGE イベント駆動）

【設計】
  以前は screeninfo で5秒ポーリングしていたが、CPU wake-up と
  DWM/GDI 競合の原因になっていたため、OS イベント駆動に変更。

  Windows がモニター構成を変更（解像度変更・回転・抜き差し）すると
  WM_DISPLAYCHANGE メッセージをブロードキャストする。
  ctypes で HWND_MESSAGE 親の隠しウィンドウを作成し、
  メッセージポンプでこれを受信して向き変化を判定する。

  待機中の CPU 使用率は実質 0%（GetMessage がブロッキング）。

【パフォーマンス改善 2026-02-23】
  ポーリング（5秒間隔）を完全廃止 → イベント駆動化。
"""

import ctypes
import ctypes.wintypes
import logging
import threading
from typing import Callable

from monitor import get_monitors, MonitorInfo, orientations_changed

logger = logging.getLogger("la_byle")

# ── Windows 定数 ──────────────────────────────────────────────
_WM_DISPLAYCHANGE = 0x007E
_WM_QUIT          = 0x0012
_HWND_MESSAGE     = ctypes.wintypes.HWND(-3)  # メッセージ専用ウィンドウの親
_CS_HREDRAW       = 0x0002
_CS_VREDRAW       = 0x0001

# ── Win32 構造体 ──────────────────────────────────────────────
_LRESULT = ctypes.wintypes.LPARAM

_WNDPROC = ctypes.WINFUNCTYPE(
    _LRESULT,                # LRESULT
    ctypes.wintypes.HWND,    # hWnd
    ctypes.c_uint,           # uMsg
    ctypes.wintypes.WPARAM,  # wParam
    ctypes.wintypes.LPARAM,  # lParam
)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize",        ctypes.c_uint),
        ("style",         ctypes.c_uint),
        ("lpfnWndProc",   _WNDPROC),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     ctypes.wintypes.HINSTANCE),
        ("hIcon",         ctypes.wintypes.HICON),
        ("hCursor",       ctypes.wintypes.HICON),
        ("hbrBackground", ctypes.wintypes.HBRUSH),
        ("lpszMenuName",  ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm",       ctypes.wintypes.HICON),
    ]


class OrientationWatcher:
    """
    WM_DISPLAYCHANGE を受信してモニター向き変化を検知するウォッチャー。

    外部インターフェース（start / stop / on_change）は旧ポーリング版と互換。
    """

    _CLASS_NAME = "LaByle_DisplayWatcher"

    def __init__(self, on_change: Callable) -> None:
        """
        on_change: 向き変化検知時に呼ばれるコールバック (引数なし)
        """
        self._on_change = on_change
        self._thread:   threading.Thread | None = None
        self._hwnd:     ctypes.wintypes.HWND | None = None
        self._prev:     list[MonitorInfo] = []
        self._running   = threading.Event()
        # _wndproc_ref: コールバック関数への参照を保持して GC を防ぐ
        self._wndproc_ref: _WNDPROC | None = None

    def start(self) -> None:
        """バックグラウンドスレッドで WM_DISPLAYCHANGE 監視を開始する。
        既に実行中の場合は何もしない。
        """
        if self._running.is_set():
            logger.debug("[Watcher] 既に実行中のため start() をスキップ")
            return
        self._running.set()
        self._prev = get_monitors()
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()
        logger.info("[Watcher] 開始（WM_DISPLAYCHANGE イベント駆動）")

    def stop(self) -> None:
        """メッセージループを停止する。"""
        self._running.clear()
        if self._hwnd is not None:
            try:
                ctypes.windll.user32.PostMessageW(
                    self._hwnd, _WM_QUIT, 0, 0
                )
            except Exception:
                pass
        logger.info("[Watcher] 停止")

    # ── メッセージループ（ワーカースレッド） ─────────────────

    def _message_loop(self) -> None:
        """
        隠しウィンドウを作成し、メッセージポンプを回す。
        WM_DISPLAYCHANGE を受信したら向き変化を判定してコールバック。
        GetMessageW はメッセージが来るまでブロッキングするため、
        待機中の CPU 使用率は実質 0%。
        """
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 64bit環境でポインタが切り詰められないよう型を明示
        user32.DefWindowProcW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.c_uint,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM
        ]
        user32.DefWindowProcW.restype = _LRESULT

        hInstance = kernel32.GetModuleHandleW(None)

        # ── WndProc ──
        def wndproc(hwnd, msg, wparam, lparam):
            if msg == _WM_DISPLAYCHANGE:
                self._on_display_change()
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        # コールバックへの参照を保持（GC 防止）
        self._wndproc_ref = _WNDPROC(wndproc)

        # ── ウィンドウクラス登録 ──
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.style = _CS_HREDRAW | _CS_VREDRAW
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hInstance
        wc.lpszClassName = self._CLASS_NAME

        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            logger.error("[Watcher] RegisterClassExW 失敗")
            return

        # ── 隠しウィンドウ作成 ──
        # HWND_MESSAGE 親にすることで画面に表示されず、
        # ブロードキャストメッセージ（WM_DISPLAYCHANGE）を受信できる
        self._hwnd = user32.CreateWindowExW(
            0,                     # dwExStyle
            self._CLASS_NAME,      # lpClassName
            "LaByle_Watcher",      # lpWindowName
            0,                     # dwStyle
            0, 0, 0, 0,           # x, y, width, height
            _HWND_MESSAGE,         # hWndParent
            None,                  # hMenu
            hInstance,             # hInstance
            None,                  # lpParam
        )

        if not self._hwnd:
            logger.error("[Watcher] CreateWindowExW 失敗")
            user32.UnregisterClassW(self._CLASS_NAME, hInstance)
            return

        logger.debug(f"[Watcher] 隠しウィンドウ作成完了: HWND={self._hwnd}")

        # ── メッセージポンプ ──
        msg = ctypes.wintypes.MSG()
        try:
            while self._running.is_set():
                ret = user32.GetMessageW(
                    ctypes.byref(msg), self._hwnd, 0, 0
                )
                if ret <= 0:
                    # 0 = WM_QUIT, -1 = エラー → ループ終了
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            logger.error(f"[Watcher] メッセージループエラー: {e}")
        finally:
            # ── クリーンアップ ──
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
                self._hwnd = None
            user32.UnregisterClassW(self._CLASS_NAME, hInstance)
            self._wndproc_ref = None
            logger.debug("[Watcher] クリーンアップ完了")

    # ── 内部 ────────────────────────────────────────────────

    def _on_display_change(self) -> None:
        """
        WM_DISPLAYCHANGE 受信時の処理。
        モニターの向き（縦/横）が変化していたらコールバックを呼ぶ。
        """
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
            logger.error(f"[Watcher] ディスプレイ変更処理エラー: {e}")
