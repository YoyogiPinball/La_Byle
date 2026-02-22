# -*- coding: utf-8 -*-
"""
wallpaper.py — IDesktopWallpaper COM API 経由での壁紙設定

【設計判断】
  Python の標準ライブラリには IDesktopWallpaper の型定義が存在しない。
  comtypes で GUID/IUnknown を継承してインターフェースを手動定義する。
  user32.SystemParametersInfoW では全モニター一括変更しかできないため、
  COM を使うことがモニター個別設定の唯一の正攻法。
"""

import ctypes
import os
import random

import comtypes
import comtypes.client
from comtypes import COMMETHOD, HRESULT

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


def _create_idwp() -> _IDesktopWallpaper:
    """
    COM オブジェクトを生成して返す。
    スレッドごとに CoInitialize が必要なため明示的に呼ぶ。
    """
    comtypes.CoInitialize()
    return comtypes.client.CreateObject(_CLSID, interface=_IDesktopWallpaper)


def _list_images(folder: str) -> list[str]:
    """folder 内（サブフォルダー含む）の対応画像ファイル一覧を返す。"""
    if not folder or not os.path.isdir(folder):
        return []
    result = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in _IMAGE_EXTS:
                result.append(os.path.join(root, f))
    return result


def apply_random(landscape_folder: str, portrait_folder: str) -> dict[str, str]:
    """
    各モニターの向きに合ったフォルダからランダムに1枚選び壁紙を設定する。

    戻り値: { device_path: applied_file_path, ... }
    設定できなかったモニターはエラーメッセージを値として格納する。

    【GetMonitorDevicePathAt について】
      SetWallpaper の第1引数はデバイスパス文字列（例: \\?\DISPLAY#...）。
      整数インデックスを直接渡せない仕様のため、
      GetMonitorDevicePathAt(i) でパスを取得してから SetWallpaper に渡す。
    """
    from monitor import get_monitors

    dwp = _create_idwp()
    monitors = get_monitors()
    results: dict[str, str] = {}

    for mon in monitors:
        try:
            device_path = dwp.GetMonitorDevicePathAt(mon.index)
            folder = (
                landscape_folder if mon.orientation.startswith("横")
                else portrait_folder
            )
            images = _list_images(folder)
            if not images:
                results[device_path] = f"[SKIP] 画像なし: {folder}"
                continue
            chosen = random.choice(images)
            dwp.SetWallpaper(device_path, os.path.normpath(chosen))
            results[device_path] = chosen
        except comtypes.COMError as e:
            results[f"monitor[{mon.index}]"] = (
                f"[COM ERROR] 0x{e.hresult & 0xFFFFFFFF:08X} {e.text}"
            )
        except Exception as e:
            results[f"monitor[{mon.index}]"] = f"[ERROR] {e}"

    return results


def set_single(device_path: str, file_path: str) -> None:
    """指定デバイスパスのモニターに指定ファイルを壁紙として設定する。"""
    dwp = _create_idwp()
    dwp.SetWallpaper(device_path, os.path.normpath(file_path))
