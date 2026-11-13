"""Одна проверяемая запись на совершённый переход."""

import copy
import os
from pathlib import Path

from .contracts import canonical


class Journal:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.records = []

    def append(self, record):
        record = copy.deepcopy(record)
        data = canonical(record) + "\n"
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        self.records.append(record)

    def snapshot(self):
        return copy.deepcopy(self.records)
