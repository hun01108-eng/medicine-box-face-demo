"""Run CLI with console output and a bounded rotating log (5 x 20 MiB)."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
log_dir = root.parents[1] / "logs"
os.umask(0o077)
handler = RotatingFileHandler(log_dir / "facebox.log", maxBytes=20 * 1024 * 1024,
                              backupCount=4, encoding="utf-8")
logger = logging.getLogger("facebox")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONUNBUFFERED="1")
try:
    with subprocess.Popen([sys.executable, "-m", "facebox.app", *sys.argv[1:]],
                          cwd=root, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True) as process:
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                logger.info(line.rstrip())
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            code = 130
finally:
    handler.close()
sys.exit(code)
