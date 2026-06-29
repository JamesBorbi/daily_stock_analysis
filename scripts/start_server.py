"""Helper script to start the DSA Web server in background."""
import subprocess
import sys
import time
import os

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8000"
    log_path = os.path.join(os.path.dirname(__file__), "..", "logs", "server_web.txt")
    
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", port],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
        )
        print(f"Server started, PID: {proc.pid}, port: {port}")
        print(f"Access: http://127.0.0.1:{port}")

if __name__ == "__main__":
    main()
