# -*- coding: utf-8 -*-
# run.pyw — コンソールなし起動エントリーポイント
# pythonw.exe がこのファイルを実行するため、コンソールウィンドウが開かない。
# デバッグ時は: python main.py --debug
import runpy
runpy.run_path(__file__.replace("run.pyw", "main.py"), run_name="__main__")
