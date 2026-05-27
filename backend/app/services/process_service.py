from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from backend.app.models.job_models import JobRuntime
from backend.app.services.constants import REPO_ROOT
from backend.app.services.store import JOBS


def start_synpp_process(runtime_config_path: Path, log_path: Path) -> subprocess.Popen[str]:
    log_file = log_path.open("w", encoding="utf-8")
    command = ["uv", "run", "-m", "synpp", str(runtime_config_path)]
    return subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def register_job_runtime(job_id: str, runtime: JobRuntime) -> None:
    JOBS[job_id] = runtime


def get_job_runtime(job_id: str) -> JobRuntime | None:
    return JOBS.get(job_id)


def stop_running_jobs_on_shutdown() -> None:
    for runtime in JOBS.values():
        process = runtime.process
        if process.poll() is not None:
            continue
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
