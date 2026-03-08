# -*- coding: utf-8 -*-
"""
wallpaper.py — IDesktopWallpaper COM API 経由での壁紙設定

【設計判断】
  Python の標準ライブラリには IDesktopWallpaper の型定義が存在しない。
  comtypes で GUID/IUnknown を継承してインターフェースを手動定義する。
  user32.SystemParametersInfoW では全モニター一括変更しかできないため、
  COM を使うことがモニター個別設定の唯一の正攻法。

【パフォーマンス改善 2026-02-23】
  - WallpaperWorker: 専用スレッドで COM を1回だけ初期化し再利用。
    CoInitialize/CoUninitialize のペアリングを保証し、COMリソースリークを防止。
  - _ImageCache: os.walk() の結果をキャッシュし、毎回のディレクトリ走査を廃止。
"""

import ctypes
import logging
import os
import queue
import random
import threading
import time

import comtypes
import comtypes.client
from comtypes import COMMETHOD, HRESULT

logger = logging.getLogger("la_byle")

# ── CLSID / IID ───────────────────────────────────────────────
_CLSID = comtypes.GUID("{C2CF3110-460E-4fc1-B9D0-8A1C0C9CC4BD}")
_IID   = comtypes.GUID("{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}")

# サポートする拡張子
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class _IDesktopWallpaper(comtypes.IUnknown):
    """
    IDesktopWallpaper COM インターフェース最小定義。
    vtable 順序は Microsoft Docs 準拠:
      SetWallpaper → GetWallpaper → GetMonitorDevicePathAt → GetMonitorDevicePathCount
    comtypes の IUnknown が QI/AddRef/Release を自動管理するため、
    _methods_ には IDesktopWallpaper 固有のメソッドのみを並べる。
    """
    _iid_ = _IID
    _methods_ = [
        COMMETHOD([], HRESULT, "SetWallpaper",
            (["in"],  ctypes.c_wchar_p, "monitorID"),
            (["in"],  ctypes.c_wchar_p, "wallpaper")),
        COMMETHOD([], HRESULT, "GetWallpaper",
            (["in"],  ctypes.c_wchar_p, "monitorID"),
            (["out"], ctypes.POINTER(ctypes.c_wchar_p), "wallpaper")),
        COMMETHOD([], HRESULT, "GetMonitorDevicePathAt",
            (["in"],  ctypes.c_uint,                    "monitorIndex"),
            (["out"], ctypes.POINTER(ctypes.c_wchar_p), "monitorID")),
        COMMETHOD([], HRESULT, "GetMonitorDevicePathCount",
            (["out"], ctypes.POINTER(ctypes.c_uint),    "count")),
    ]


# ── 画像一覧キャッシュ ────────────────────────────────────────
class _ImageCache:
    """
    フォルダーパスをキーに画像ファイル一覧をキャッシュする。
    毎回 os.walk() するのを防ぎ、I/O を削減する。

    キャッシュの寿命:
      - 同じフォルダーパスが渡される限りキャッシュを返す
      - invalidate() / invalidate_all() で明示的にクリア
      - TTL（30分）経過で自動的に再スキャン
    """

    _TTL_SEC = 30 * 60  # 30分

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, list[str]]] = {}

    def get(self, folder: str) -> list[str]:
        """folder 内の画像ファイル一覧を返す。キャッシュがあればそれを使う。"""
        if not folder or not os.path.isdir(folder):
            return []

        now = time.monotonic()
        if folder in self._store:
            cached_at, files = self._store[folder]
            if now - cached_at < self._TTL_SEC:
                return files

        # キャッシュミス → 走査
        files = self._scan(folder)
        self._store[folder] = (now, files)
        logger.debug(f"[ImageCache] スキャン: {folder} → {len(files)}件")
        return files

    def invalidate(self, folder: str) -> None:
        """特定フォルダーのキャッシュを破棄する。"""
        self._store.pop(folder, None)

    def invalidate_all(self) -> None:
        """全キャッシュを破棄する（設定保存時に呼ぶ想定）。"""
        self._store.clear()
        logger.debug("[ImageCache] 全キャッシュクリア")

    @staticmethod
    def _scan(folder: str) -> list[str]:
        """folder 内（サブフォルダー含む）の対応画像ファイル一覧を返す。"""
        result = []
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in _IMAGE_EXTS:
                    result.append(os.path.join(root, f))
        return result


# ── シーケンシャルカウンター ──────────────────────────────────

class _WallpaperSequencer:
    """
    モニターごとに順番カウンターを管理する。

    キー: monitor_index（フォルダではなく画面単位）
    リセット条件: モニター台数 or 向きのいずれかが変化したとき
    """

    def __init__(self) -> None:
        self._counters: dict[int, int] = {}  # monitor_index → next_idx
        self._signature: str = ""            # "0:横,1:横,2:縦" 形式

    def check_reset(self, monitors) -> None:
        """モニター構成が変わっていたらカウンターを全リセットする。"""
        sig = ",".join(
            f"{m.index}:{m.orientation}"
            for m in sorted(monitors, key=lambda m: m.index)
        )
        if sig != self._signature:
            self._counters.clear()
            self._signature = sig
            logger.debug(f"[Sequencer] リセット: {sig}")

    def next_image(self, monitor_index: int, images: list[str]) -> str:
        """
        images（ソート済み前提）から次の1枚を返しカウンターを進める。
        images が空の場合は空文字列を返す。
        初回はランダムなオフセットからスタートし、同フォルダを共有する
        複数モニターが同じ画像を選び続けるのを防ぐ。
        """
        if not images:
            return ""
        if monitor_index not in self._counters:
            self._counters[monitor_index] = random.randrange(len(images))
        idx = self._counters[monitor_index] % len(images)
        self._counters[monitor_index] = idx + 1
        return images[idx]


# ── 壁紙適用の内部ロジック ─────────────────────────────────────

def _apply_sequential_impl(
    dwp: _IDesktopWallpaper,
    cache: _ImageCache,
    sequencer: _WallpaperSequencer,
    landscape_folder: str,
    portrait_folder: str,
) -> dict[str, str]:
    """
    全モニターに対して、各モニターのカウンター順で次の1枚を設定する。

    戻り値: { device_path: applied_file_path, ... }
    設定できなかったモニターはエラーメッセージを値として格納する。
    """
    from monitor import get_monitors

    monitors = get_monitors()
    sequencer.check_reset(monitors)
    results: dict[str, str] = {}

    t_total = time.perf_counter()
    for mon in monitors:
        try:
            device_path = dwp.GetMonitorDevicePathAt(mon.index)
            folder = (
                landscape_folder if mon.orientation.startswith("横")
                else portrait_folder
            )
            images = sorted(cache.get(folder))
            if not images:
                results[device_path] = f"[SKIP] 画像なし: {folder}"
                continue
            chosen = sequencer.next_image(mon.index, images)
            t = time.perf_counter()
            dwp.SetWallpaper(device_path, os.path.normpath(chosen))
            logger.debug(
                f"[Wallpaper] SetWallpaper[{mon.index}] {time.perf_counter() - t:.3f}s"
                f" → {os.path.basename(chosen)}"
            )
            results[device_path] = chosen
        except comtypes.COMError as e:
            results[f"monitor[{mon.index}]"] = (
                f"[COM ERROR] 0x{e.hresult & 0xFFFFFFFF:08X} {e.text}"
            )
        except Exception as e:
            results[f"monitor[{mon.index}]"] = f"[ERROR] {e}"

    logger.debug(f"[Wallpaper] 全モニター合計: {time.perf_counter() - t_total:.3f}s")
    return results


def _apply_next_single_impl(
    dwp: _IDesktopWallpaper,
    cache: _ImageCache,
    monitor_index: int,
    landscape_folder: str,
    portrait_folder: str,
) -> dict[str, str]:
    """
    指定 index のモニター1台だけをランダムに選んだ画像に変更する。
    画像ゼロの場合は SKIP。
    """
    from monitor import get_monitors

    monitors = get_monitors()
    results: dict[str, str] = {}

    target = next((m for m in monitors if m.index == monitor_index), None)
    if target is None:
        return {f"monitor[{monitor_index}]": "[ERROR] not found"}

    try:
        device_path = dwp.GetMonitorDevicePathAt(target.index)
        folder = (
            landscape_folder if target.orientation.startswith("横")
            else portrait_folder
        )
        images = cache.get(folder)
        if not images:
            return {device_path: f"[SKIP] 画像なし: {folder}"}
        chosen = random.choice(images)
        t = time.perf_counter()
        dwp.SetWallpaper(device_path, os.path.normpath(chosen))
        logger.debug(
            f"[Wallpaper] SetWallpaper[{target.index}] {time.perf_counter() - t:.3f}s"
            f" → {os.path.basename(chosen)}"
        )
        results[device_path] = chosen
    except comtypes.COMError as e:
        results[f"monitor[{monitor_index}]"] = (
            f"[COM ERROR] 0x{e.hresult & 0xFFFFFFFF:08X} {e.text}"
        )
    except Exception as e:
        results[f"monitor[{monitor_index}]"] = f"[ERROR] {e}"

    return results


# ── 壁紙ワーカースレッド ───────────────────────────────────────

# リクエスト種別
_REQ_APPLY            = "apply"
_REQ_SINGLE           = "single"
_REQ_NEXT_SINGLE      = "next_single"
_REQ_NEXT_ALL         = "next_all"
_REQ_SHUTDOWN         = "shutdown"
_REQ_INVALIDATE_CACHE = "invalidate_cache"


class WallpaperWorker:
    """
    壁紙適用処理を専用スレッドに集約するワーカー。

    【設計意図】
      COM (IDesktopWallpaper) はスレッドごとに CoInitialize() が必要で、
      使い終わったら CoUninitialize() を呼ばないとリソースリークが起きる。
      ワーカースレッドを1本立てて、その中だけで COM を使うことで
      初期化/破棄を1回ずつに抑え、リークを完全に防止する。

      「次へ」ボタンやスケジューラからのリクエストはキューに投入し、
      ワーカーが順次処理する。最新のリクエストのみ保持する設計で、
      連打時も最後の1回だけが実行される。
    """

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._cache = _ImageCache()
        self._sequencer = _WallpaperSequencer()

    def start(self) -> None:
        """ワーカースレッドを開始する。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("[WallpaperWorker] 開始")

    def shutdown(self) -> None:
        """ワーカースレッドを停止する。"""
        self._queue.put((_REQ_SHUTDOWN, None, None))
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info("[WallpaperWorker] 停止")

    def submit_apply(
        self,
        landscape_folder: str,
        portrait_folder: str,
        callback=None,
    ) -> None:
        """
        壁紙適用リクエストをキューに投入する。
        キュー内に既存の apply リクエストがあれば破棄して最新のみ残す。
        callback: 結果を受け取る関数 (results: dict) → None
        """
        # キューをドレインして未処理の apply リクエストを破棄（最新リクエスト優先）
        # ※ queue.empty() はマルチスレッド下で信頼性が低いが、
        #    直後の get_nowait() と queue.Empty 例外キャッチによって
        #    安全にドレインできているため実用上の問題はない。
        drained = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item[0] != _REQ_APPLY:
                    drained.append(item)  # shutdown 等は保持
            except queue.Empty:
                break
        for item in drained:
            self._queue.put(item)

        self._queue.put((
            _REQ_APPLY,
            (landscape_folder, portrait_folder),
            callback,
        ))

    def submit_single(
        self,
        device_path: str,
        file_path: str,
    ) -> None:
        """指定デバイスパスのモニターに壁紙を設定するリクエストを投入する。"""
        self._queue.put((_REQ_SINGLE, (device_path, file_path), None))

    def submit_next_single(
        self,
        monitor_index: int,
        landscape_folder: str,
        portrait_folder: str,
        callback=None,
    ) -> None:
        """「次の壁紙へ → 1枚ずつ」: 指定モニター1台のみランダムに変更する。"""
        self._queue.put((
            _REQ_NEXT_SINGLE,
            (monitor_index, landscape_folder, portrait_folder),
            callback,
        ))

    def submit_next_all(
        self,
        landscape_folder: str,
        portrait_folder: str,
        callback=None,
    ) -> None:
        """「次の壁紙へ → 全部」: 全モニターを次の画像に変更する。"""
        self._queue.put((_REQ_NEXT_ALL, (landscape_folder, portrait_folder), callback))

    def invalidate_cache(self) -> None:
        """画像キャッシュを全クリアする（設定保存時に呼ぶ）。"""
        self._queue.put((_REQ_INVALIDATE_CACHE, None, None))

    @staticmethod
    def _log_results(results: dict) -> None:
        for dev, path in results.items():
            if path.startswith("[SKIP]"):
                logger.info(f"  SKIP {dev}: {path}")
            elif path.startswith("["):
                logger.warning(f"  {dev} → {path}")
            else:
                logger.info(f"  {dev} → {os.path.basename(path)}")

    # ── ワーカースレッド本体 ─────────────────────────────────

    def _run(self) -> None:
        """
        ワーカースレッドのメインループ。
        COM の初期化→ループ→破棄を1スレッド内で完結させる。
        """
        # ── COM 初期化（このスレッドで1回だけ） ──
        comtypes.CoInitialize()
        logger.debug("[WallpaperWorker] CoInitialize 完了")

        dwp: _IDesktopWallpaper | None = None
        try:
            dwp = comtypes.client.CreateObject(
                _CLSID, interface=_IDesktopWallpaper
            )
            logger.debug("[WallpaperWorker] IDesktopWallpaper 取得完了")

            while True:
                req_type, args, callback = self._queue.get()

                if req_type == _REQ_SHUTDOWN:
                    break

                if req_type == _REQ_INVALIDATE_CACHE:
                    self._cache.invalidate_all()
                    continue

                if req_type == _REQ_APPLY:
                    land, port = args
                    try:
                        results = _apply_sequential_impl(
                            dwp, self._cache, self._sequencer, land, port
                        )
                        if callback:
                            try:
                                callback(results)
                            except Exception as e:
                                logger.error(
                                    f"[WallpaperWorker] callback エラー: {e}"
                                )
                    except Exception as e:
                        logger.error(
                            f"[WallpaperWorker] 壁紙適用エラー: {e}"
                        )

                elif req_type == _REQ_NEXT_ALL:
                    land, port = args
                    try:
                        results = _apply_sequential_impl(
                            dwp, self._cache, self._sequencer, land, port
                        )
                        self._log_results(results)
                        if callback:
                            try:
                                callback(results)
                            except Exception as e:
                                logger.error(
                                    f"[WallpaperWorker] next_all callback エラー: {e}"
                                )
                    except Exception as e:
                        logger.error(
                            f"[WallpaperWorker] next_all エラー: {e}"
                        )

                elif req_type == _REQ_NEXT_SINGLE:
                    mon_idx, land, port = args
                    try:
                        results = _apply_next_single_impl(
                            dwp, self._cache, mon_idx, land, port
                        )
                        self._log_results(results)
                        if callback:
                            try:
                                callback(results)
                            except Exception as e:
                                logger.error(
                                    f"[WallpaperWorker] next_single callback エラー: {e}"
                                )
                    except Exception as e:
                        logger.error(
                            f"[WallpaperWorker] next_single エラー: {e}"
                        )

                elif req_type == _REQ_SINGLE:
                    device_path, file_path = args
                    try:
                        dwp.SetWallpaper(
                            device_path, os.path.normpath(file_path)
                        )
                    except Exception as e:
                        logger.error(
                            f"[WallpaperWorker] 個別設定エラー: {e}"
                        )

        except Exception as e:
            logger.error(f"[WallpaperWorker] 致命的エラー: {e}")
        finally:
            # ── COM オブジェクト解放 ──
            if dwp is not None:
                del dwp
            # ── COM 終了化（CoInitialize とペアで必ず呼ぶ） ──
            try:
                comtypes.CoUninitialize()
                logger.debug("[WallpaperWorker] CoUninitialize 完了")
            except Exception:
                pass
