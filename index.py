import sys
import argparse
import threading
import time
import urllib.parse

from PySide6.QtWidgets import QApplication

from main_window import MainWindow
from api import run_server

DEFAULT_PORT = 32764

# Time to wait after starting the Flask thread before opening the browser.
# Flask binds its socket asynchronously; without this delay the browser may
# attempt to connect before the server is ready.
_FLASK_STARTUP_DELAY = 0.5


def main():
    parser = argparse.ArgumentParser(
        description="PyTorch Memory Profiler – web-based viewer"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        metavar="PORT",
        help=(
            f"Port for the local REST API server "
            f"(default: {DEFAULT_PORT}, bound to 127.0.0.1)"
        ),
    )
    parser.add_argument(
        "pickle_path",
        nargs="?",
        default=None,
        help="Optional path to a pickle file to open on startup",
    )
    args = parser.parse_args()

    # Start the REST API server in a background daemon thread
    server_thread = threading.Thread(
        target=run_server,
        args=(args.port,),
        daemon=True,
    )
    server_thread.start()

    # Give Flask a moment to bind its socket before the browser navigates
    time.sleep(_FLASK_STARTUP_DELAY)

    # Build the startup URL; pass pickle path as a query parameter when given
    base_url = f"http://127.0.0.1:{args.port}/"
    if args.pickle_path:
        url = base_url + "?pickle=" + urllib.parse.quote(
            args.pickle_path, safe=""
        )
    else:
        url = base_url

    qt_app = QApplication(sys.argv)
    win = MainWindow(url=url)
    win.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
