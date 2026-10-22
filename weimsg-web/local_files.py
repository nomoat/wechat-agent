"""Index the attachment files WeChat has already saved on this Mac.

Message metadata still comes from the snapshot, but file bytes are never read
from DuckDB. This index maps an opaque token to a path under WeChat's own
``msg/file`` and ``msg/video`` directories. HTTP streaming always goes through
a token; file messages additionally expose the indexed absolute path in the
snapshot (and in DuckDB's ``local_files`` table) so Electron can locate the
file without scanning WeChat's directory again.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".log", ".xml", ".yaml", ".yml",
    ".py", ".js", ".ts", ".html", ".css", ".sh",
}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
PDF_EXTENSIONS = {".pdf"}
SKIPPED_SUFFIXES = {".tmp", ".part", ".download", ".crdownload"}
PREVIEWABLE_CATEGORIES = {"image", "video", "audio", "pdf", "text"}


def category_for(name: str) -> str:
    """Return a coarse category used by the UI and by content disposition."""
    suffix = Path(str(name or "")).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if suffix in OFFICE_EXTENSIONS:
        return "office"
    if suffix in ARCHIVE_EXTENSIONS:
        return "archive"
    return "other"


def is_previewable(category: str) -> bool:
    return category in PREVIEWABLE_CATEGORIES


def token_for(relative_path: str) -> str:
    return hashlib.sha1(relative_path.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LocalFileEntry:
    token: str
    relative_path: str
    name: str
    size: int
    mtime: float
    category: str
    absolute_path: str = ""

    def to_dict(self) -> dict:
        """Serialize without the host path; local-files.json stays relative."""
        return {
            "token": self.token,
            "relative_path": self.relative_path,
            "name": self.name,
            "size": self.size,
            "mtime": self.mtime,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LocalFileEntry":
        relative = str(data.get("relative_path") or "")
        name = str(data.get("name") or Path(relative).name)
        return cls(
            token=str(data.get("token") or token_for(relative)),
            relative_path=relative,
            name=name,
            size=int(data.get("size") or 0),
            mtime=float(data.get("mtime") or 0),
            category=str(data.get("category") or category_for(name)),
            absolute_path=str(data.get("absolute_path") or ""),
        )


def _is_video_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return True
    return not suffix and bool(re.fullmatch(r"[0-9a-fA-F]{32}", path.name))


def discover_local_files(root: Path | str | None) -> list[LocalFileEntry]:
    """Scan ``<root>/<account>/msg/{file,video}`` for saved attachments.

    ``root`` is the WeChat ``xwechat_files`` directory (the same path the
    Docker container mounts read-only). Thumbnails and partial downloads are
    skipped; saved files are indexed whether or not a message references them.
    """
    if not root:
        return []
    root = Path(root).expanduser()
    if not root.is_dir():
        return []
    entries: list[LocalFileEntry] = []
    seen: set[str] = set()
    for account in sorted(item for item in root.iterdir() if item.is_dir()):
        for folder in ("msg/file", "msg/video"):
            base = account / folder
            if not base.is_dir():
                continue
            is_video_dir = folder == "msg/video"
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                name = path.name
                if name.startswith(".") or path.suffix.lower() in SKIPPED_SUFFIXES:
                    continue
                if is_video_dir and not _is_video_file(path):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size <= 0:
                    continue
                relative = path.relative_to(root).as_posix()
                if relative in seen:
                    continue
                seen.add(relative)
                category = "video" if is_video_dir and not path.suffix else category_for(name)
                entries.append(
                    LocalFileEntry(
                        token=token_for(relative),
                        relative_path=relative,
                        name=name,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        category=category,
                        absolute_path=str(path.resolve()),
                    )
                )
    return entries


class LocalFileIndex:
    """Look up saved files by token, or attach a message to a local file."""

    def __init__(self, entries: list[LocalFileEntry] | None = None):
        self.entries = list(entries or [])
        self.by_token = {entry.token: entry for entry in self.entries}
        self._by_name: dict[str, list[LocalFileEntry]] = {}
        for entry in self.entries:
            self._by_name.setdefault(entry.name.casefold(), []).append(entry)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, token: str) -> LocalFileEntry | None:
        return self.by_token.get(token)

    def match(
        self, name: str, size: int | None = None, month: str | None = None
    ) -> LocalFileEntry | None:
        """Match a message attachment to a saved file by name and byte size."""
        plain_name = Path(str(name or "")).name
        candidates = self._by_name.get(plain_name.casefold(), [])
        exact = candidates
        try:
            wanted_size = int(size or 0)
        except (TypeError, ValueError):
            wanted_size = 0
        if wanted_size > 0:
            exact = [entry for entry in candidates if entry.size == wanted_size]
        if month:
            in_month = [
                entry for entry in exact
                if f"/{month}/" in f"/{entry.relative_path}"
            ]
            exact = in_month or exact
        if exact:
            return exact[0]
        if wanted_size <= 0:
            return candidates[0] if len(candidates) == 1 else None
        suffix = Path(plain_name).suffix.lower()
        same_ext = [
            entry for entry in self.entries
            if entry.size == wanted_size and entry.name.lower().endswith(suffix)
        ] if suffix else []
        return same_ext[0] if len(same_ext) == 1 else None

    def duckdb_records(self, root: Path | str | None) -> list[dict]:
        """Return the host index rows persisted in the DuckDB archive."""
        if not root:
            return []
        base = Path(root).expanduser().resolve()
        records = []
        for entry in self.entries:
            absolute = entry.absolute_path or str((base / entry.relative_path).resolve())
            records.append(
                {
                    "token": entry.token,
                    "relative_path": entry.relative_path,
                    "absolute_path": absolute,
                    "name": entry.name,
                    "size": entry.size,
                    "mtime": entry.mtime,
                    "category": entry.category,
                }
            )
        return records

    def match_video(self, size: int | None) -> LocalFileEntry | None:
        try:
            wanted = int(size or 0)
        except (TypeError, ValueError):
            return None
        if wanted <= 0:
            return None
        for entry in self.entries:
            if entry.category == "video" and entry.size == wanted:
                return entry
        return None

    def write(self, data_dir: Path) -> Path:
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = data_dir / "local-files.json"
        temporary = data_dir / "local-files.json.tmp"
        payload = {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": {
                entry.token: entry.to_dict()
                for entry in sorted(self.entries, key=lambda item: item.relative_path)
            },
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return target

    @classmethod
    def load(cls, data_dir: Path) -> "LocalFileIndex":
        path = Path(data_dir) / "local-files.json"
        if not path.is_file():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(files, dict):
            return cls()
        entries = []
        for token, data in files.items():
            if not isinstance(data, dict):
                continue
            entry = LocalFileEntry.from_dict({**data, "token": token})
            if entry.relative_path:
                entries.append(entry)
        return cls(entries)


def resolve_entry(root: Path | str | None, entry: LocalFileEntry) -> Path | None:
    """Resolve an indexed entry under ``root``; reject traversal and dirs."""
    if not root:
        return None
    base = Path(root).expanduser().resolve()
    target = (base / entry.relative_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target if target.is_file() else None
