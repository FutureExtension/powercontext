"""Configuration of the research desk.

Every value comes from the environment so that the runbook can configure the
service without editing source, and so that no credential is ever stored in
the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "qoder"
SAMPLE_DIR = APP_DIR / "sample"


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    seekdb_host: str
    seekdb_port: int
    seekdb_user: str
    seekdb_password: str
    seekdb_database: str
    state_path: Path
    sample_dir: Path
    host: str
    port: int
    scope: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            seekdb_host=os.environ.get("DESK_SEEKDB_HOST", "127.0.0.1"),
            seekdb_port=int(os.environ.get("DESK_SEEKDB_PORT", "2883")),
            seekdb_user=os.environ.get("DESK_SEEKDB_USER", "root"),
            seekdb_password=os.environ.get("DESK_SEEKDB_PASSWORD", ""),
            seekdb_database=os.environ.get("DESK_SEEKDB_DATABASE", "research_desk"),
            state_path=Path(
                os.environ.get(
                    "DESK_STATE_PATH", str(APP_DIR / "state" / "research-desk.db")
                )
            ),
            sample_dir=Path(os.environ.get("DESK_SAMPLE_DIR", str(SAMPLE_DIR))),
            host=os.environ.get("DESK_HOST", "127.0.0.1"),
            port=int(os.environ.get("DESK_PORT", "8848")),
            scope=os.environ.get("DESK_SCOPE", "research-desk"),
        )
