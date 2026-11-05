from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Gesture-to-PC backend (always binds to 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="Open the app in the default browser")
    parser.add_argument("--no-frontend", action="store_true", help="Serve the API only (use the Vite dev server on :5173)")
    args = parser.parse_args(argv)

    import uvicorn

    from app.logging_config import uvicorn_log_config
    from app.main import create_app
    from app.settings.config import AppConfig
    from app.settings.paths import AppPaths

    config = AppConfig(paths=AppPaths.default(), port=args.port, serve_frontend=not args.no_frontend)
    app = create_app(config)
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    uvicorn.run(app, host=config.host, port=args.port, log_level="info", log_config=uvicorn_log_config(), ws_ping_interval=20, ws_ping_timeout=20)


if __name__ == "__main__":
    main()
