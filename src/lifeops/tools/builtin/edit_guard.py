from __future__ import annotations

from pathlib import Path


class FileEditGuard:
    """跟踪 Agent 会话内已读取过的文件，强制“先读后编辑”。

    目的：防止模型在未观察文件真实内容的情况下凭想象修改文件。
    Agent 每次运行共享一个 guard 实例，reset() 清空。
    """

    def __init__(self) -> None:
        self._read_files: set[str] = set()

    def _normalize(self, path: str | Path) -> str:
        return str(Path(path).expanduser().resolve())

    def mark_read(self, path: str | Path) -> None:
        self._read_files.add(self._normalize(path))

    def has_read(self, path: str | Path) -> bool:
        return self._normalize(path) in self._read_files

    def reset(self) -> None:
        self._read_files.clear()
