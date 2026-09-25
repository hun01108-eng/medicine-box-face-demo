"""多场景智能药箱比赛演示调度程序。

本模块只编排已有的人脸、红外、流感 API 和 Uno 通信能力，不复制核心算法。
每个步骤独立记录，单项失败不会阻止后续模块展示。模拟模式不会访问真实硬件。
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .flu_api import FluApiClient
from .uno import UNO_BAUD, UnoNotifier


AUDIO_LABELS = {
    "0004": "有人经过，请吃药",
    "0005": "人脸识别成功",
    "0006": "人脸识别失败",
    "0007": "体温过高",
    "0008": "体温正常",
    "0009": "流感高风险",
    "0010": "流感中风险",
    "0011": "流感低风险",
}


@dataclass(frozen=True)
class DemoConfig:
    app_config: str = "config.json"
    uno_port: str = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
    thermal_port: str = "/dev/serial/by-id/replace-with-mlx90642-device"
    cloud_url: str = "http://192.144.163.230"
    web_url: str = "http://192.144.163.230"
    face_timeout_seconds: float = 30.0
    thermal_timeout_seconds: float = 60.0
    medicine_command: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    name: str
    status: str
    message: str
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)


def load_demo_config(path: Path) -> DemoConfig:
    """读取不含密钥的演示配置，并拒绝未知字段。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = DemoConfig(**payload)
    if config.face_timeout_seconds <= 0 or config.thermal_timeout_seconds <= 0:
        raise ValueError("演示超时时间必须大于0")
    return config


class CompetitionDemo:
    """按比赛展示顺序调用各子系统并生成汇总日志。"""

    def __init__(self, root: Path, config: DemoConfig, log_dir: Path) -> None:
        self.root = root
        self.config = config
        self.log_dir = log_dir
        self.results: list[StepResult] = []
        self.python = sys.executable
        self.environment = os.environ.copy()
        source = str(root / "src")
        current = self.environment.get("PYTHONPATH", "")
        self.environment["PYTHONPATH"] = source + (os.pathsep + current if current else "")

    def _command(self, *arguments: str) -> list[str]:
        return [
            self.python,
            "-m",
            "facebox.app",
            "--config",
            str(self.root / self.config.app_config),
            *arguments,
        ]

    @staticmethod
    def _json_lines(output: str) -> list[dict]:
        records = []
        for line in output.splitlines():
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def _record(
        self,
        name: str,
        status: str,
        message: str,
        started: float,
        details: dict[str, Any] | None = None,
    ) -> StepResult:
        result = StepResult(
            name=name,
            status=status,
            message=message,
            duration_seconds=round(time.monotonic() - started, 3),
            details=details or {},
        )
        self.results.append(result)
        icon = {"passed": "[通过]", "failed": "[失败]", "skipped": "[跳过]", "simulated": "[模拟]"}.get(status, "[信息]")
        print(f"{icon} {name}：{message}", flush=True)
        return result

    def _run_process(
        self,
        name: str,
        command: list[str],
        timeout: float,
        accepted_codes: set[int] | None = None,
    ) -> StepResult:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                env=self.environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._record(name, "failed", f"超过{timeout:g}秒未完成", started)
        output = "\n".join(value for value in (completed.stdout.strip(), completed.stderr.strip()) if value)
        if output:
            print(output, flush=True)
        accepted = accepted_codes or {0}
        status = "passed" if completed.returncode in accepted else "failed"
        message = "执行完成" if status == "passed" else f"退出码 {completed.returncode}"
        return self._record(
            name,
            status,
            message,
            started,
            {"return_code": completed.returncode, "records": self._json_lines(output)},
        )

    def self_check(self) -> StepResult:
        """检查模型、模板、设备路径、云端和药品适配器配置。"""
        started = time.monotonic()
        checks: dict[str, Any] = {}
        face = subprocess.run(
            self._command("self-check"),
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        checks["face"] = {
            "ready": face.returncode == 0,
            "records": self._json_lines(face.stdout),
        }
        checks["uno_port"] = {
            "path": self.config.uno_port,
            "exists": Path(self.config.uno_port).exists(),
        }
        checks["thermal_port"] = {
            "path": self.config.thermal_port,
            "exists": Path(self.config.thermal_port).exists(),
        }
        try:
            cache = self.root / "data" / "demo_flu_risk_cache.json"
            status = FluApiClient(self.config.cloud_url, 5.0, cache).fetch_latest()
            checks["cloud_api"] = {
                "ready": True,
                "report_week": status.report_week,
                "risk_level": status.risk_level,
                "source": status.source,
                "stale": status.stale,
            }
        except RuntimeError as error:
            checks["cloud_api"] = {"ready": False, "reason": str(error)}
        checks["medicine"] = {
            "configured": bool(self.config.medicine_command),
            "command": self.config.medicine_command,
        }
        required = (
            checks["face"]["ready"],
            checks["uno_port"]["exists"],
            checks["thermal_port"]["exists"],
            checks["cloud_api"]["ready"],
        )
        return self._record(
            "系统自检",
            "passed" if all(required) else "failed",
            "核心设备与服务正常" if all(required) else "存在未就绪项目，请查看详情",
            started,
            checks,
        )

    def face(self, display: bool = False) -> StepResult:
        command = self._command(
            "run",
            "--source",
            "opencv",
            "--uno-port",
            self.config.uno_port,
        )
        if display:
            command.append("--display")
        # UNKNOWN/RETRY属于有效的安全拒绝结果，不视为程序崩溃。
        return self._run_process(
            "人脸识别",
            command,
            self.config.face_timeout_seconds,
            accepted_codes={0, 2, 3},
        )

    def thermal(self) -> StepResult:
        """运行红外监测，获得首个PERSON_IN事件后结束该展示步骤。"""
        started = time.monotonic()
        command = self._command(
            "thermal-monitor",
            "--thermal-port",
            self.config.thermal_port,
            "--uno-port",
            self.config.uno_port,
        )
        process = subprocess.Popen(
            command,
            cwd=self.root,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        messages: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                messages.put(line)
            messages.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        records = []
        deadline = time.monotonic() + self.config.thermal_timeout_seconds
        try:
            while time.monotonic() < deadline:
                try:
                    line = messages.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                if line is None:
                    break
                print(line.rstrip(), flush=True)
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
                    if record.get("event") == "PERSON_IN":
                        return self._record("红外经过与体温", "passed", "检测并播报完成", started, record)
            reason = "红外程序提前退出" if process.poll() is not None else "等待人员经过超时"
            return self._record("红外经过与体温", "failed", reason, started, {"records": records})
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()

    def medicine(self) -> StepResult:
        started = time.monotonic()
        if not self.config.medicine_command:
            return self._record(
                "药品识别",
                "skipped",
                "未配置独立药品识别命令",
                started,
            )
        return self._run_process(
            "药品识别",
            self.config.medicine_command,
            timeout=30.0,
        )

    def flu(self, force: bool = True) -> StepResult:
        command = self._command(
            "flu-audio",
            "--api-base-url",
            self.config.cloud_url,
            "--uno-port",
            self.config.uno_port,
        )
        if force:
            command.append("--force")
        return self._run_process("流感风险预警", command, timeout=30.0)

    def serial(self, audio_code: str) -> StepResult:
        started = time.monotonic()
        if audio_code not in AUDIO_LABELS:
            return self._record("串口音频", "failed", f"不支持的编号 {audio_code}", started)
        notifier = None
        try:
            notifier = UnoNotifier(self.config.uno_port, UNO_BAUD)
            acknowledged = notifier.notify(f"{audio_code}\n".encode("ascii"))
            return self._record(
                "串口音频",
                "passed" if acknowledged else "failed",
                f"{audio_code} {AUDIO_LABELS[audio_code]}，ACK={'成功' if acknowledged else '失败'}",
                started,
                {"audio_code": audio_code, "uno_ack": acknowledged},
            )
        except (OSError, ValueError, RuntimeError) as error:
            return self._record("串口音频", "failed", str(error), started)
        finally:
            if notifier is not None:
                notifier.close()

    def simulate(self) -> list[StepResult]:
        """生成明确标注的完整模拟流程，不打开设备或访问网络。"""
        simulations = [
            ("系统自检", "模拟环境检查完成", {"simulation": True}),
            ("红外经过与体温", "检测到人员，36.6°C，音频0004/0008", {"audio_codes": ["0004", "0008"], "peak_temperature": 36.6}),
            ("人脸识别", "MATCHED elder_001，音频0005", {"status": "MATCHED", "user_id": "elder_001", "audio_code": "0005"}),
            ("药品识别", "独立模块模拟结果：等待正式适配", {"configured": bool(self.config.medicine_command)}),
            ("流感风险预警", "中风险，音频0010", {"risk_level": "中", "audio_code": "0010"}),
            ("云端网页", self.config.web_url, {"url": self.config.web_url}),
        ]
        for name, message, details in simulations:
            self._record(name, "simulated", message, time.monotonic(), details)
        return self.results

    def run(self, display: bool = False, open_web: bool = False) -> list[StepResult]:
        """执行完整实机演示；每步失败后继续下一步。"""
        self.self_check()
        for step in (self.thermal, lambda: self.face(display), self.medicine, self.flu):
            try:
                step()
            except Exception as error:
                # 演示调度层必须隔离单模块故障，同时保留可审查的错误信息。
                self._record("未完成步骤", "failed", str(error), time.monotonic())
        if open_web:
            opened = webbrowser.open(self.config.web_url)
            self._record(
                "云端网页",
                "passed" if opened else "failed",
                self.config.web_url,
                time.monotonic(),
            )
        else:
            self._record("云端网页", "passed", self.config.web_url, time.monotonic())
        return self.results

    def save_summary(self, mode: str) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.log_dir / f"demo_{timestamp}.json"
        payload = {
            "project": "多场景AI智能药箱",
            "mode": mode,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "results": [asdict(result) for result in self.results],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="多场景AI智能药箱比赛演示程序")
    result.add_argument("--demo-config", default="demo_config.json")
    result.add_argument("--log-dir", type=Path, default=Path("logs"))
    commands = result.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="按顺序运行完整实机演示")
    run.add_argument("--display", action="store_true", help="显示人脸识别窗口")
    run.add_argument("--open-web", action="store_true", help="尝试打开云端网页")
    commands.add_parser("simulate", help="不访问硬件和网络的完整模拟")
    commands.add_parser("self-check")
    face = commands.add_parser("face")
    face.add_argument("--display", action="store_true")
    commands.add_parser("thermal")
    commands.add_parser("medicine")
    flu = commands.add_parser("flu")
    flu.add_argument("--no-force", action="store_true", help="同一周已播报时跳过")
    serial = commands.add_parser("serial")
    serial.add_argument("--code", required=True, choices=sorted(AUDIO_LABELS))
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    config_path = Path(arguments.demo_config).resolve()
    root = config_path.parent
    log_dir = arguments.log_dir if arguments.log_dir.is_absolute() else root / arguments.log_dir
    demo = CompetitionDemo(root, load_demo_config(config_path), log_dir)
    print("=" * 60)
    print("多场景 AI 智能药箱比赛演示系统")
    print(f"模式：{arguments.command}")
    print("=" * 60)
    try:
        if arguments.command == "run":
            demo.run(arguments.display, arguments.open_web)
        elif arguments.command == "simulate":
            demo.simulate()
        elif arguments.command == "self-check":
            demo.self_check()
        elif arguments.command == "face":
            demo.face(arguments.display)
        elif arguments.command == "thermal":
            demo.thermal()
        elif arguments.command == "medicine":
            demo.medicine()
        elif arguments.command == "flu":
            demo.flu(force=not arguments.no_force)
        else:
            demo.serial(arguments.code)
    except (FileNotFoundError, ValueError, RuntimeError, OSError) as error:
        demo._record("演示程序", "failed", str(error), time.monotonic())
    summary = demo.save_summary(arguments.command)
    failed = sum(result.status == "failed" for result in demo.results)
    print("-" * 60)
    print(f"演示记录：{summary}")
    print(f"结果：{len(demo.results) - failed}项完成，{failed}项失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
