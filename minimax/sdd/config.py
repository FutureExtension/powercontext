"""Configuration of the SDD context module.

Every value comes from the environment so that the runbook can configure the
module without editing source, and so that no credential is ever stored in the
repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MINIMAX_DIR = REPO_ROOT / "minimax"
SAMPLE_PROJECT = MINIMAX_DIR / "sample_project"


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    seekdb_host: str
    seekdb_port: int
    seekdb_user: str
    seekdb_password: str
    seekdb_database: str
    state_path: Path
    sample_project: Path
    minimax_api_key: str | None
    minimax_base_url: str
    minimax_model: str

    @property
    def has_minimax_key(self) -> bool:
        return bool(self.minimax_api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            seekdb_host=os.environ.get("SDD_SEEKDB_HOST", "127.0.0.1"),
            seekdb_port=int(os.environ.get("SDD_SEEKDB_PORT", "2884")),
            seekdb_user=os.environ.get("SDD_SEEKDB_USER", "root"),
            seekdb_password=os.environ.get("SDD_SEEKDB_PASSWORD", ""),
            seekdb_database=os.environ.get("SDD_SEEKDB_DATABASE", "sdd"),
            state_path=Path(
                os.environ.get("SDD_STATE_PATH", str(MINIMAX_DIR / "state" / "sdd-state.db"))
            ),
            sample_project=Path(
                os.environ.get("SDD_SAMPLE_PROJECT", str(SAMPLE_PROJECT))
            ),
            minimax_api_key=os.environ.get("MINIMAX_API_KEY") or None,
            minimax_base_url=os.environ.get(
                "MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"
            ),
            minimax_model=os.environ.get("MINIMAX_MODEL", "MiniMax-Text-01"),
        )
