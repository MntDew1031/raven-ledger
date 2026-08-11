import os
import subprocess
import sys


subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    check=True,
)
os.execvp(
    "uvicorn",
    [
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--proxy-headers",
    ],
)
