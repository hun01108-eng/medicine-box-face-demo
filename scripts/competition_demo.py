#!/usr/bin/env python3
"""比赛演示程序入口；从源码目录运行时自动加载 ``src``。"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from facebox.demo import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
