from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Gesture-to-PC backend (binds to 127.0.0.1; --hosted serves the public online demo instead)")
    parser.add_argument("--port", type=int, default=None, help="Default 8000; with --hosted the default is $PORT, else 10000")
    parser.add_argument("--open", action="store_true", help="Open the app in the default browser")
    parser.add_argument("--no-frontend", action="store_true", help="Serve the API only (use the Vite dev server on :5173)")
    parser.add_argument("--hosted", action="store_true", help="Public online demo: a private Demo Mode sandbox per visitor, no real sensors and no PC control")
    args = parser.parse_args(argv)

    import uvicorn

    from app.logging_config import uvicorn_log_config
    from app.main import create_app
    from app.settings.config import DEFAULT_PORT, AppConfig, hosted_config
    from app.settings.paths import AppPaths

    if args.hosted:
        from app.hosting.app import configure_hosted_logging

        configure_hosted_logging()
        config = hosted_config(AppPaths.default(), port=args.port, serve_frontend=not args.no_frontend)
        app = create_app(config)
        uvicorn.run(app, host=config.host, port=config.port, log_level="info", log_config=uvicorn_log_config(), ws_ping_interval=20, ws_ping_timeout=20, proxy_headers=True, forwarded_allow_ips="*")
        return

    port = args.port or DEFAULT_PORT
    config = AppConfig(paths=AppPaths.default(), port=port, serve_frontend=not args.no_frontend)
    app = create_app(config)
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    uvicorn.run(app, host=config.host, port=port, log_level="info", log_config=uvicorn_log_config(), ws_ping_interval=20, ws_ping_timeout=20)


if __name__ == "__main__":
    main()
