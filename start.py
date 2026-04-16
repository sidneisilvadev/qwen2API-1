#!/usr/bin/env python3
"""
qwen2API Enterprise Gateway Startup Script

Frontend: Vite dev server  http://localhost:5174
Backend: uvicorn          http://localhost:7860  (API Gateway)
"""
import os
import sys
import subprocess
import time
import signal
from pathlib import Path

WORKSPACE_DIR = Path(__file__).parent.absolute()
BACKEND_DIR = WORKSPACE_DIR / "backend"
FRONTEND_DIR = WORKSPACE_DIR / "frontend"
LOGS_DIR = WORKSPACE_DIR / "logs"
DATA_DIR = WORKSPACE_DIR / "data"

# Auto-detect virtual environment
VENV_PYTHON = WORKSPACE_DIR / "venv" / "Scripts" / "python.exe" if os.name == "nt" else WORKSPACE_DIR / "venv" / "bin" / "python"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

def ensure_dirs():
    LOGS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)

def check_python():
    print(f"Using Python: {PYTHON_EXE}")
    if sys.version_info < (3, 10) and not VENV_PYTHON.exists():
        print("[ERROR] Requires Python 3.10+, current version:", sys.version)
        sys.exit(1)

def install_backend_deps():
    print("[1/4] Installing backend dependencies...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKSPACE_DIR)
    try:
        subprocess.check_call(
            [PYTHON_EXE, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
            cwd=BACKEND_DIR,
            env=env,
        )
        print("[SUCCESS] Backend dependencies ready")
    except Exception as e:
        print(f"[WARNING] Backend dependencies installation error: {e}")

def fetch_browser():
    print("[2/4] Ensuring Chromium browser engine is ready...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKSPACE_DIR)
    try:
        # Check if chromium is already installed via playwright
        subprocess.check_call(
            [PYTHON_EXE, "-m", "playwright", "install", "chromium"],
            cwd=WORKSPACE_DIR,
            env=env,
        )
        print("[SUCCESS] Chromium engine ready")
    except Exception as e:
        print(f"[WARNING] Chromium auto-installation error (might already exist): {e}")

def start_frontend() -> subprocess.Popen:
    print("[3/4] Starting frontend development server...")
    is_windows = os.name == "nt"

    # Pre-emptively kill any process on the standard vite port
    kill_port(5174)

    if not (FRONTEND_DIR / "node_modules").exists():
        print("  -> Running npm install...")
        try:
            subprocess.check_call(
                "npm install" if is_windows else ["npm", "install"],
                cwd=FRONTEND_DIR,
                shell=is_windows,
            )
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] npm install failed: {e}")
            sys.exit(1)

    proc = subprocess.Popen(
        "npm run dev" if is_windows else ["npm", "run", "dev"],
        cwd=FRONTEND_DIR,
        shell=is_windows,
    )
    print(f"[SUCCESS] Frontend started (PID: {proc.pid}) -> http://127.0.0.1:5174")
    return proc

def kill_port(port: int):
    """Kill any process occupying the given port."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    pid = line.strip().split()[-1]
                    if pid.isdigit() and pid != '0':
                        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True)
                        print(f"  -> Terminated process cluster on port {port} (PID: {pid})")
                        time.sleep(2) # Give it more time to release
                        return
        else:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True, text=True, timeout=5
            )
            pid = result.stdout.strip()
            if pid:
                subprocess.run(["kill", "-9", pid], capture_output=True)
                print(f"  -> Terminated old process on port {port} (PID: {pid})")
                time.sleep(1)
    except Exception:
        pass

def start_backend() -> subprocess.Popen:
    print("[4/4] Starting backend service...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKSPACE_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    port = env.get("PORT", "7860")
    kill_port(int(port))

    proc = subprocess.Popen(
        [
            PYTHON_EXE, "-m", "uvicorn",
            "backend.main:app",
            "--host", "0.0.0.0",
            "--port", port,
            "--workers", "1",
        ],
        cwd=WORKSPACE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    print(f"[SUCCESS] Backend process started (PID: {proc.pid}), initializing browser engine...")

    import threading
    ready_event = threading.Event()

    def read_output():
        for line in iter(proc.stdout.readline, b""):
            try:
                decoded = line.decode("utf-8", errors="replace")
                # Ensure no characters that CP1252 doesn't like on Windows
                if os.name == "nt":
                    safe_output = decoded.encode("cp1252", errors="replace").decode("cp1252")
                else:
                    safe_output = decoded
                print(safe_output, end="", flush=True)
                if "Lite Browser engine started" in safe_output or "Application startup complete" in safe_output:
                    ready_event.set()
            except Exception as e:
                # Silently fail on print errors to keep the thread alive
                pass

    threading.Thread(target=read_output, daemon=True).start()

    started = ready_event.wait(timeout=300)
    if not started:
        print("[WARNING] Backend initialization timed out, service might not be fully ready")
    else:
        print("[SUCCESS] Service is fully ready")

    return proc

def main():
    ensure_dirs()
    check_python()
    install_backend_deps()
    fetch_browser()
    backend_proc = start_backend()   
    frontend_proc = start_frontend() 

    port = os.environ.get("PORT", "7860")
    print()
    print("=" * 50)
    print("  qwen2API is now online")
    print(f"  Frontend WebUI:   http://127.0.0.1:5174")
    print(f"  Backend API:      http://127.0.0.1:{port}")
    print("=" * 50)
    print("  Press Ctrl+C to stop all services")
    print()

    def signal_handler(sig, frame):
        print("\nShutting down services...")
        for p in (backend_proc, frontend_proc):
            try:
                p.terminate()
            except Exception:
                pass
        backend_proc.wait()
        print("Services stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while True:
            if backend_proc.poll() is not None:
                print(f"[ERROR] Backend process exited unexpectedly (Exit Code: {backend_proc.returncode})")
                break
            if frontend_proc.poll() is not None:
                print(f"[ERROR] Frontend process exited unexpectedly (Exit Code: {frontend_proc.returncode})")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in (backend_proc, frontend_proc):
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass

if __name__ == "__main__":
    main()
