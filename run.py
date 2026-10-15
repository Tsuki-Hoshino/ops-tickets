"""启动入口：启动 waitress 服务。"""

import argparse
import os

from waitress import serve

from app import create_app
from app.config import DEFAULT_HOST, DEFAULT_PORT


def parse_args():
    parser = argparse.ArgumentParser(description="运维工单与报告系统")
    parser.add_argument(
        "--host",
        default=os.environ.get("OPS_HOST", DEFAULT_HOST),
        help="监听地址，默认 0.0.0.0（内网可访问）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OPS_PORT", DEFAULT_PORT)),
        help="监听端口，默认 8080",
    )
    parser.add_argument("--threads", type=int, default=8, help="工作线程数")
    parser.add_argument(
        "--open-browser", action="store_true", help="启动后自动打开浏览器"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    app = create_app()
    local_url = f"http://127.0.0.1:{args.port}/"
    print("=" * 52)
    print("  运维工单与报告系统")
    print(f"  本机访问：{local_url}")
    print(f"  内网访问：http://<本机IP>:{args.port}/")
    print("  按 Ctrl+C 停止服务")
    print("=" * 52)
    if args.open_browser:
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(local_url)).start()
    serve(app, host=args.host, port=args.port, threads=args.threads)


if __name__ == "__main__":
    main()
