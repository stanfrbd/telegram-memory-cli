"""Short-lived browser downloads, isolated from the persistent archive directory."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path


class BrowserDownloads:
    def __init__(self, ttl: int = 1800):
        self.ttl = ttl
        self.files: dict[str, tuple[tempfile.TemporaryDirectory, Path, float]] = {}

    def expire(self) -> None:
        for job_id, (_, _, deadline) in list(self.files.items()):
            if time.monotonic() >= deadline:
                self.remove(job_id)

    def add(self, job_id: str, directory: tempfile.TemporaryDirectory, path: Path) -> None:
        self.expire()
        if not path.resolve().is_relative_to(Path(directory.name).resolve()):
            directory.cleanup()
            raise ValueError("Downloaded file is outside the temporary directory.")
        self.files[job_id] = (directory, path, time.monotonic() + self.ttl)

    def get(self, job_id: str) -> Path | None:
        self.expire()
        entry = self.files.get(job_id)
        return entry[1] if entry and entry[1].is_file() else None

    def remove(self, job_id: str) -> None:
        entry = self.files.pop(job_id, None)
        if entry:
            entry[0].cleanup()

    def close(self) -> None:
        for job_id in list(self.files):
            self.remove(job_id)
