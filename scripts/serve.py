"""Start DepthWizard (backend + built viewer) on this computer; open the browser once it is ready.

python scripts/serve.py                          # http://127.0.0.1:8000, opens the browser
python scripts/serve.py --port 8765 --no-browser # as the desktop app's backend (sidecar)
"""

import argparse
import threading
import time
import webbrowser

import requests
import uvicorn

HOST = "127.0.0.1"  # a local app: never listen on other network interfaces
READY_TIMEOUT_S = 180  # the model loads once at startup; CPU-only machines take a while


def open_when_ready(url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{url}/api/health", timeout=2).ok:
                webbrowser.open(url)
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    print(f"The backend did not answer within {READY_TIMEOUT_S} s; open {url} yourself.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python scripts/serve.py")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://{HOST}:{args.port}"
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    print(f"DepthWizard on {url}  (Ctrl+C to stop)")
    uvicorn.run("api.main:app", host=HOST, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
