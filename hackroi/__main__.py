import argparse
import json
import signal
import threading
from pathlib import Path

from . import __version__
from .audit import audit, read_records
from .contracts import ProtocolError, export
from .controller import Controller
from .environment import Environment
from .http import ControllerApplication, EnvironmentApplication, make_server


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Ариадна — каркас протокола Метарой 1.0")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("environment", "controller"):
        child = sub.add_parser(command)
        child.add_argument("--host", default="127.0.0.1")
        child.add_argument("--port", type=int, default=8000 if command == "environment" else 8001)
        child.add_argument("--log-path", type=Path)
        if command == "environment":
            child.add_argument("--map-file", type=Path, help="Карта ariadna.map.v1; фиксируется до reset")
        if command == "controller":
            child.add_argument("--environment-url")
            child.add_argument("--seed", type=int, default=42)
            child.add_argument("--max-decisions", type=int, default=100)
            child.add_argument("--run-id")
            child.add_argument("--decision-delay", type=float, default=0., help="Пауза визуализации в секундах, 0–1; не меняет модельное время")
            mode = child.add_mutually_exclusive_group()
            mode.add_argument("--baseline", choices=["fixed", "reactive"])
            mode.add_argument("--meta", action="store_true", help="Метаконтроллер третьего этапа")
            mode.add_argument("--portable", action="store_true", help="Переносимый контроллер пятого этапа")
            mode.add_argument("--counterfactual", action="store_true", help="Контрфактический штаб четвёртого этапа")
    schema_parser = sub.add_parser("export-schemas")
    schema_parser.add_argument("--output", type=Path, default=Path("contracts"))
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--environment-log", required=True, type=Path)
    audit_parser.add_argument("--controller-log", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "export-schemas":
        export(args.output)
        return 0
    if args.command == "audit":
        emit(audit(read_records(args.environment_log), read_records(args.controller_log)))
        return 0
    component = Environment(args.log_path, json.loads(args.map_file.read_text(encoding="utf-8")) if args.map_file else None) if args.command == "environment" else Controller(args.log_path)
    if args.command == "controller" and args.baseline:
        from .baselines import FixedController, ReactiveController
        component = (FixedController if args.baseline == "fixed" else ReactiveController)(args.log_path)
    if args.command == "controller" and args.meta:
        from .metacontroller import MetaController
        component = MetaController(args.log_path)
    if args.command == "controller" and args.counterfactual:
        from .counterfactual import CounterfactualController
        component = CounterfactualController(args.log_path)
    if args.command == "controller" and args.portable:
        from .portable import PortableController
        component = PortableController(args.log_path)
    if args.command == "controller":
        if not 0 <= args.decision_delay <= 1:
            parser.error("--decision-delay: от 0 до 1")
        component.decision_delay = args.decision_delay
    application = EnvironmentApplication(component) if args.command == "environment" else ControllerApplication(component)
    server = make_server(application, args.host, args.port)
    stop = threading.Event()
    def request_stop(*_args):
        stop.set()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    emit({"event": "ready", "component": args.command,
          "url": f"http://{args.host}:{server.server_address[1]}", "protocol_version": "1.0"})
    exit_code = 0
    try:
        if args.command == "controller" and args.environment_url:
            try:
                summary = component.run(args.environment_url, args.seed, args.max_decisions, args.run_id)
                emit({"event": "episode_complete", **summary})
            except ProtocolError as error:
                emit({"event": "error", **error.payload()})
                return 1
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
