"""Spec-Driven Development context module.

The module answers one question for an AI development assistant: *given a task,
which specifications, code and tests belong to the context, and what has already
been done?*  Two stores provide the answer:

* seekdb holds the engineering material (specifications, code symbols, tests)
  and answers the retrieval with a native fulltext query;
* PowerContext holds the task state, so a later run can resume the work.
"""

from sdd.config import Settings
from sdd.context import ContextBundle, build_context
from sdd.state import TaskRecord, TaskStateStore
from sdd.store import MaterialStore

__all__ = (
    "ContextBundle",
    "MaterialStore",
    "Settings",
    "TaskRecord",
    "TaskStateStore",
    "build_context",
)
