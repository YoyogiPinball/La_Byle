# -*- coding: utf-8 -*-
"""
startup.py — Windows スタートアップ登録（winreg 経由）

登録先: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
  → 管理者権限不要・ユーザーごとの登録

【実行コマンド】
  - .exe ビルド時: sys.executable のパスを直接登録
  - 開発実行時  : "python.exe main.py" の形式で登録
"""

import os
import sys
import winreg
import logging

logger = logging.getLogger("la_byle")

APP_NAME = "La_Byle"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _exe_command() -> str:
    """
    レジストリに登録するコマンド文字列を返す。
    - PyInstaller .exe: exe のフルパスのみ
    - 開発実行中   : pythonw.exe + run.pyw のフルパス
      .pyw を使うことでコンソールウィンドウなしで常駐できる。
      .venv\\Scripts\\pythonw.exe が存在すればそれを優先して使用する。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller でビルドされた .exe
        return f'"{sys.executable}"'
    else:
        project_root = os.path.dirname(os.path.abspath(__file__))
        venv_pythonw = os.path.join(project_root, ".venv", "Scripts", "pythonw.exe")
        venv_python  = os.path.join(project_root, ".venv", "Scripts", "python.exe")

        if os.path.exists(venv_pythonw):
            py = venv_pythonw
        elif os.path.exists(venv_python):
            py = venv_python
        else:
            py = sys.executable

        script = os.path.join(project_root, "run.pyw")
        return f'"{py}" "{script}"'



def register() -> None:
    """
    スタートアップにアプリを登録する。
    すでに登録されている場合は上書きする（パスが変わっても正しく更新される）。
    """
    cmd = _exe_command()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY,
            0, winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        logger.info(f"[Startup] 登録: {cmd}")
    except OSError as e:
        logger.error(f"[Startup] 登録失敗: {e}")
        raise RuntimeError(f"スタートアップ登録に失敗しました: {e}") from e


def unregister() -> None:
    """
    スタートアップからアプリを削除する。
    未登録の場合は何もしない（エラーにならない）。
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY,
            0, winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
                logger.info("[Startup] 登録解除")
            except FileNotFoundError:
                logger.debug("[Startup] 未登録のため解除スキップ")
    except OSError as e:
        logger.error(f"[Startup] 解除失敗: {e}")
        raise RuntimeError(f"スタートアップ登録の解除に失敗しました: {e}") from e


def is_registered() -> bool:
    """現在スタートアップに登録されているか確認する。"""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY,
            0, winreg.KEY_READ,
        ) as key:
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except FileNotFoundError:
                return False
    except OSError:
        return False
