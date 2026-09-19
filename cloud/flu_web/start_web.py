#!/usr/bin/env python3
"""启动本地网站并自动在默认浏览器中打开首页。"""

import getpass
import os
import threading
import webbrowser

from app import app
from ai_flu_alert import validate_api_key
from database import ensure_schema


def open_browser():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("尚未读取到 DEEPSEEK_API_KEY。")
        api_key = getpass.getpass("请在这里输入 DeepSeek API Key（输入内容不会显示）：").strip()
        if api_key:
            try:
                os.environ["DEEPSEEK_API_KEY"] = validate_api_key(api_key)
                print("本次运行已加载 API Key。")
            except RuntimeError as exc:
                print(f"API Key 无效：{exc}")
                print("请重新运行 start_web.py，并只粘贴以 sk- 开头的密钥。")
                raise SystemExit(1)
        else:
            print("未输入 API Key；网页可以查看周报，但不能生成 AI 月报。")
    else:
        try:
            os.environ["DEEPSEEK_API_KEY"] = validate_api_key(
                os.environ["DEEPSEEK_API_KEY"]
            )
        except RuntimeError as exc:
            print(f"环境变量中的 API Key 无效：{exc}")
            raise SystemExit(1)
    ensure_schema()
    threading.Timer(1.2, open_browser).start()
    print("网站正在启动：http://127.0.0.1:5000")
    print("关闭网站请在本窗口按 Ctrl+C")
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
