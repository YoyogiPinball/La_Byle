# -*- coding: utf-8 -*-
"""
monitor.py — モニター情報取得・向き判定
"""

import ctypes
import ctypes.wintypes
import logging
from dataclasses import dataclass


# ── EnumDisplayDevicesW でフレンドリー名取得 ─────────────────
class _DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb",           ctypes.c_ulong),
        ("DeviceName",   ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags",   ctypes.c_ulong),
        ("DeviceID",     ctypes.c_wchar * 128),
        ("DeviceKey",    ctypes.c_wchar * 128),
    ]


_GENERIC_NAMES = {
    "generic pnp monitor",
    "generic non-pnp monitor",
    "generic monitor",
}


def _friendly_name(adapter_name: str, index: int) -> str:
    """
    アダプター名から接続されたモニターのフレンドリー名を取得する。
    返り値が汎用名（"Generic PnP Monitor" 等）の場合は
    「ディスプレイ N」に差し替えて返す。
    実際のモデル名（"LG TV" 等）が取れた場合はそれを使う。
    """
    try:
        dd = _DISPLAY_DEVICE()
        dd.cb = ctypes.sizeof(dd)
        if ctypes.windll.user32.EnumDisplayDevicesW(
            adapter_name, 0, ctypes.byref(dd), 0
        ):
            name = dd.DeviceString.strip()
            if name and name.lower() not in _GENERIC_NAMES:
                return name
    except Exception:
        pass
    return f"ディスプレイ {index + 1}"


@dataclass
class MonitorInfo:
    index:       int
    name:        str          # フレンドリー名
    width:       int
    height:      int
    x:           int
    y:           int
    orientation: str          # "横 (Landscape)" or "縦 (Portrait)"


def get_monitors() -> list[MonitorInfo]:
    """
    screeninfo でシステムのモニター一覧を取得し、
    フレンドリー名と向き判定を付けて返す。
    向き判定: width > height → 横、それ以外 → 縦
    """
    try:
        from screeninfo import get_monitors as _get
        result = []
        for i, m in enumerate(_get()):
            orientation = (
                "横 (Landscape)" if m.width > m.height else "縦 (Portrait)"
            )
            name = _friendly_name(m.name, i) if m.name else f"ディスプレイ {i + 1}"
            result.append(MonitorInfo(
                index=i,
                name=name,
                width=m.width,
                height=m.height,
                x=m.x,
                y=m.y,
                orientation=orientation,
            ))
        return result
    except Exception as e:
        logging.getLogger("la_byle").warning(f"[Monitor] モニター情報取得に失敗: {e}")
        return []


def orientations_changed(prev: list[MonitorInfo],
                         curr: list[MonitorInfo]) -> bool:
    """向き（縦/横）や台数が変化したか比較する。"""
    if len(prev) != len(curr):
        return True
    return any(a.orientation != b.orientation for a, b in zip(prev, curr))
