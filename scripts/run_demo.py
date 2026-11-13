"""Два независимых процесса, проверка HTTP, завершённый эпизод и аудит."""

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hackroi.audit import audit, read_records
from hackroi.client import Client


class Process:
    def __init__(self, arguments):
        self.process = subprocess.Popen([sys.executable, "-u", "-m", "hackroi", *arguments],
                                        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8",
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        self.lines = queue.Queue()
        self.stderr = []
        def read_stdout():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)
        def read_stderr():
            self.stderr.extend(self.process.stderr.readlines())
        self.threads = [threading.Thread(target=read_stdout, daemon=True),
                        threading.Thread(target=read_stderr, daemon=True)]
        for thread in self.threads:
            thread.start()

    def event(self, expected, timeout=15):
        while True:
            try:
                line = self.lines.get(timeout=timeout)
            except queue.Empty as error:
                raise RuntimeError("Нет ответа дочернего процесса: " + expected) from error
            if line is None:
                self.process.wait(timeout=2)
                raise RuntimeError("Дочерний процесс завершился: " + "".join(self.stderr))
            value = json.loads(line)
            if value.get("event") == "error":
                raise RuntimeError(str(value))
            if value.get("event") == expected:
                return value

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        for thread in self.threads:
            thread.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()


def run(seed=42, output=None):
    output = Path(output).resolve() if output else ROOT / "artifacts" / ("demo_" + uuid.uuid4().hex[:10])
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Каталог результатов должен быть пустым")
    environment = controller = None
    try:
        environment = Process(["environment", "--port", "0", "--log-path", str(output / "environment.jsonl")])
        environment_ready = environment.event("ready")
        env_client = Client(environment_ready["url"])
        if env_client.get("health")["status"] != "ready":
            raise RuntimeError("Среда не готова")
        controller = Process(["controller", "--port", "0", "--environment-url", environment_ready["url"],
                              "--seed", str(seed), "--run-id", "demo_" + str(seed),
                              "--log-path", str(output / "controller.jsonl")])
        controller_ready = controller.event("ready")
        controller_health = Client(controller_ready["url"]).request("GET", "/v1/controller/health")
        if controller_health["status"] != "ready":
            raise RuntimeError("Контроллер не готов")
        summary = controller.event("episode_complete")
        if summary["status"] != "success":
            raise RuntimeError("Демонстрационная миссия не выполнена: " + str(summary))
        public_logs = env_client.get("logs")["records"]
        disk_logs = read_records(output / "environment.jsonl")
        if public_logs != disk_logs:
            raise RuntimeError("HTTP журнал отличается от файла")
        report = audit(disk_logs, read_records(output / "controller.jsonl"))
        result = {"protocol_version": "1.0", "seed": seed, "processes": 2,
                  "environment_health": "ready", "controller_health": "ready",
                  "episode": summary, "audit": report, "output_directory": str(output)}
        (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        if controller:
            controller.stop()
        if environment:
            environment.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.seed, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
