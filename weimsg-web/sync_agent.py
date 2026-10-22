"""Mirror the host DuckDB API into a read-only web snapshot.

Runs on the Mac that owns the WeChat archive. The Docker web container never
touches the DuckDB file, WeChat keys, or macOS permissions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from local_files import (
    LocalFileIndex,
    category_for,
    discover_local_files,
    is_previewable,
)

DEFAULT_HOST_API = os.getenv("HOST_API_URL", "http://127.0.0.1:8769")
DEFAULT_DATA_DIR = Path(
    os.getenv("DATA_DIR", str(Path(__file__).resolve().parent / "web-data"))
)
DEFAULT_MEDIA_SOURCE = Path(
    os.getenv(
        "MEDIA_SOURCE",
        str(
            Path.home()
            / "Library/Application Support/WeChatAgent/wechat4-export/media"
        ),
    )
)
DEFAULT_DECRYPTED_DIR = Path(
    os.getenv(
        "DECRYPTED_DIR",
        str(
            Path.home()
            / "Library/Application Support/WeChatAgent/wechat4-export/decrypted"
        ),
    )
)
DEFAULT_OUTBOX_DIR = Path(
    os.getenv("OUTBOX_DIR", str(Path(__file__).resolve().parent / "web-outbox"))
)
IMAGE_TYPE = 3
VIDEO_TYPE = 43
VOICE_TYPE = 34
FILE_SUBTYPE = 6
DEFAULT_WECHAT_ROOT = (
    Path.home()
    / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
)


def default_wechat_root() -> Path | None:
    """Return WeChat's ``xwechat_files`` root, or None when absent."""
    configured = os.getenv("WECHAT_FILES_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_WECHAT_ROOT if DEFAULT_WECHAT_ROOT.is_dir() else None


class SendWorker(threading.Thread):
    """Consume web send requests and call the host's WeChat UI send endpoint."""

    def __init__(
        self,
        host_api: str,
        outbox_dir: Path,
        interval: float = 1.0,
    ):
        super().__init__(name="weimsg-send-worker", daemon=True)
        self._host_api = host_api.rstrip("/")
        self._outbox = Path(outbox_dir).expanduser()
        self._interval = max(0.5, interval)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_once()
            except Exception as error:
                print(
                    f"[send] worker error: {type(error).__name__}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
            self._stop.wait(self._interval)

    def process_once(self) -> None:
        self._outbox.mkdir(parents=True, exist_ok=True, mode=0o700)
        for request_path in sorted(self._outbox.glob("request-*.json")):
            try:
                request = json.loads(request_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                request_path.unlink(missing_ok=True)
                continue
            request_id = str(request.get("id") or "")
            if not re.fullmatch(r"[0-9a-f]{32}", request_id):
                request_path.unlink(missing_ok=True)
                continue
            result_path = self._outbox / f"result-{request_id}.json"
            if result_path.exists():
                request_path.unlink(missing_ok=True)
                continue
            chat = request.get("chat")
            display_name = request.get("display_name")
            text = request.get("text")
            if (
                not isinstance(chat, str)
                or not chat.strip()
                or not isinstance(display_name, str)
                or not display_name.strip()
                or not isinstance(text, str)
                or not text.strip()
            ):
                self._write_result(
                    result_path,
                    {
                        "request_id": request_id,
                        "status": "failed",
                        "error": "recipient_or_text_rejected",
                    },
                )
                request_path.unlink(missing_ok=True)
                continue

            result = {
                "request_id": request_id,
                "chat": chat,
                "display_name": display_name,
                "text": text,
            }
            try:
                response = httpx.post(
                    f"{self._host_api}/send",
                    json={
                        "text": text,
                        "request_id": request_id,
                        "chat": chat,
                        "display_name": display_name,
                    },
                    timeout=90,
                )
                if response.status_code == 200:
                    data = response.json()
                    result.update(data)
                    result["status"] = (
                        "sent" if data.get("verified") else "sent_unverified"
                    )
                else:
                    detail = None
                    try:
                        detail = response.json().get("detail")
                    except Exception:
                        detail = response.text[:500]
                    result.update(
                        {
                            "status": "failed",
                            "http_status": response.status_code,
                            "detail": detail,
                        }
                    )
            except Exception as error:
                result.update(
                    {
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
            self._write_result(result_path, result)
            request_path.unlink(missing_ok=True)

    def _write_result(self, path: Path, payload: dict) -> None:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)


class FileActionWorker(threading.Thread):
    """Open or reveal local WeChat files on the Mac that owns them.

    Docker cannot run macOS ``open``; the page queues an action through the
    outbox and this host-side worker performs it.
    """

    def __init__(
        self,
        wechat_root: Path | str,
        outbox_dir: Path,
        interval: float = 1.0,
    ):
        super().__init__(name="weimsg-file-action-worker", daemon=True)
        self._root = Path(wechat_root).expanduser().resolve()
        self._outbox = Path(outbox_dir).expanduser()
        self._interval = max(0.5, interval)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_once()
            except Exception as error:
                print(
                    f"[file-action] worker error: {type(error).__name__}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
            self._stop.wait(self._interval)

    def process_once(self) -> None:
        self._outbox.mkdir(parents=True, exist_ok=True, mode=0o700)
        for request_path in sorted(self._outbox.glob("action-*.json")):
            try:
                request = json.loads(request_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                request_path.unlink(missing_ok=True)
                continue
            request_id = str(request.get("id") or "")
            if not re.fullmatch(r"[0-9a-f]{32}", request_id):
                request_path.unlink(missing_ok=True)
                continue
            result_path = self._outbox / f"action-result-{request_id}.json"
            if result_path.exists():
                request_path.unlink(missing_ok=True)
                continue
            action = str(request.get("action") or "")
            result = {
                "request_id": request_id,
                "action": action,
            }
            target = self._resolve(str(request.get("relative_path") or ""))
            if action not in {"open", "reveal"}:
                result.update({"status": "failed", "error": "unsupported_action"})
            elif target is None:
                result.update({"status": "failed", "error": "file_not_found"})
            else:
                command = ["open", str(target)]
                if action == "reveal":
                    command.insert(1, "-R")
                try:
                    completed = subprocess.run(
                        command, capture_output=True, timeout=20, check=False
                    )
                    if completed.returncode == 0:
                        result["status"] = "done"
                    else:
                        result.update(
                            {
                                "status": "failed",
                                "error": completed.stderr.decode(
                                    "utf-8", errors="replace"
                                )[:500] or f"exit_{completed.returncode}",
                            }
                        )
                except (OSError, subprocess.SubprocessError) as error:
                    result.update(
                        {
                            "status": "failed",
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
            self._write_result(result_path, result)
            request_path.unlink(missing_ok=True)

    def _resolve(self, relative_path: str) -> Path | None:
        if not relative_path or Path(relative_path).is_absolute():
            return None
        target = (self._root / relative_path).resolve()
        try:
            target.relative_to(self._root)
        except ValueError:
            return None
        return target if target.is_file() else None

    def _write_result(self, path: Path, payload: dict) -> None:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)


class ResourceResolver:
    """Map (chat, local_id, type) to the thumbnail md5 in message_resource.db."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.chat_ids = dict(
            self.connection.execute(
                "SELECT user_name, rowid FROM ChatName2Id"
            ).fetchall()
        )

    def close(self) -> None:
        self.connection.close()

    def md5(self, chat_username: str, local_id, message_type: int) -> str | None:
        chat_id = self.chat_ids.get(chat_username)
        if not chat_id:
            return None
        row = self.connection.execute(
            "SELECT packed_info FROM MessageResourceInfo "
            "WHERE chat_id=? AND message_local_id=? "
            "AND (message_local_type=? OR message_local_type % 4294967296=?) "
            "ORDER BY message_create_time DESC LIMIT 1",
            (chat_id, local_id, message_type, message_type),
        ).fetchone()
        if not row or not row[0]:
            return None
        return extract_resource_md5(row[0])


def extract_resource_md5(blob) -> str | None:
    if not isinstance(blob, bytes) or not blob:
        return None
    marker = b"\x12\x22\x0a\x20"
    index = blob.find(marker)
    if index >= 0 and index + len(marker) + 32 <= len(blob):
        candidate = blob[index + len(marker) : index + len(marker) + 32]
        try:
            value = candidate.decode("ascii")
            int(value, 16)
            return value.lower()
        except (UnicodeDecodeError, ValueError):
            pass
    match = re.search(rb"[0-9a-fA-F]{32}", blob)
    return match.group(0).decode("ascii").lower() if match else None


def fetch_all(client: httpx.Client, host_api: str) -> dict:
    base = host_api.rstrip("/")
    conversations = client.get(f"{base}/db/conversations").raise_for_status().json()[
        "conversations"
    ]
    messages_by_chat: dict[str, list[dict]] = {}
    for conversation in conversations:
        username = conversation["username"]
        response = client.get(
            f"{base}/db/messages",
            params={"chat": username, "limit": 1000},
        )
        response.raise_for_status()
        messages_by_chat[username] = response.json()["messages"]
    media = client.get(
        f"{base}/db/media", params={"limit": 1000}
    ).raise_for_status().json()["media"]
    transcripts = client.get(
        f"{base}/db/transcripts", params={"limit": 500}
    ).raise_for_status().json()["transcripts"]
    return {
        "conversations": conversations,
        "messages_by_chat": messages_by_chat,
        "media": media,
        "transcripts": transcripts,
    }


def register_local_files(
    client: httpx.Client,
    host_api: str,
    index: LocalFileIndex,
    wechat_root: Path | None,
) -> None:
    """Persist absolute local paths in DuckDB through the host API."""
    if not wechat_root:
        return
    root = Path(wechat_root).expanduser().resolve()
    payload = {"root": str(root), "files": index.duckdb_records(root)}
    try:
        response = client.post(
            f"{host_api.rstrip('/')}/db/local-files", json=payload
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        print(
            f"[sync] local file index not persisted: {type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )


def _safe_name(value: str) -> str:
    return Path(str(value or "unknown")).name or "unknown"


def prepare_media(
    media_records: list[dict], media_source: Path, data_dir: Path
) -> tuple[list[dict], dict[tuple[str, str], dict]]:
    """Copy media into the snapshot and build a (kind, name) lookup."""
    output: list[dict] = []
    lookup: dict[tuple[str, str], dict] = {}
    for record in media_records:
        source = Path(str(record.get("decoded_path") or "")).expanduser()
        kind = _safe_name(record.get("kind") or "file")
        month = _safe_name(record.get("month") or "unknown")
        name = _safe_name(record.get("name") or source.stem)
        fmt = _safe_name(record.get("format") or source.suffix.lstrip(".") or "bin")
        filename = name if name.endswith("." + fmt) else f"{name}.{fmt}"
        target_dir = data_dir / "media" / kind / month
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = target_dir / filename
        copied = False
        if source.is_file():
            try:
                if not target.is_file() or target.stat().st_size != source.stat().st_size:
                    shutil.copy2(source, target)
                copied = True
            except OSError as error:
                print(f"[sync] media copy failed {source}: {error}", file=sys.stderr)
        url = (
            "/media/" + "/".join(quote(part, safe="") for part in (kind, month, filename))
            if copied
            else None
        )
        item = {
            "kind": kind,
            "chat_username": record.get("chat_username"),
            "month": month,
            "name": name,
            "format": fmt,
            "size": record.get("size") or 0,
            "url": url,
        }
        output.append(item)
        if copied:
            lookup[(kind, name)] = item
            if record.get("chat_username"):
                lookup[(f"{kind}:{record['chat_username']}", name)] = item
    return output, lookup


def _detail(message: dict) -> dict:
    detail = message.get("detail_json")
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str) and detail:
        try:
            value = json.loads(detail)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _find_md5(value) -> str | None:
    if isinstance(value, str):
        import re

        match = re.search(r"\b[0-9a-fA-F]{32}\b", value)
        return match.group(0).lower() if match else None
    if isinstance(value, dict):
        for item in value.values():
            found = _find_md5(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_md5(item)
            if found:
                return found
    return None


def _month_of(message: dict) -> str | None:
    try:
        timestamp = int(message.get("timestamp") or 0)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m")


def _file_details(message_type: int, message: dict, detail: dict) -> dict | None:
    """Return normalized file metadata for WeChat file/app-file messages."""
    if message_type & 0xFFFFFFFF != 49:
        return None
    subtype = detail.get("subtype", message.get("subtype"))
    if subtype != FILE_SUBTYPE and "size_bytes" not in detail:
        return None
    name = Path(str(detail.get("title") or detail.get("file_name") or "")).name
    if not name:
        return None
    return {
        "name": name,
        "size": detail.get("size_bytes") or detail.get("file_size") or detail.get("size"),
        "ext": str(detail.get("ext") or Path(name).suffix.lstrip(".")).lower(),
    }


def _image_record(
    media_lookup: dict[tuple[str, str], dict], username: str, name: str
) -> dict | None:
    return media_lookup.get(
        (f"image:{username}", name)
    ) or media_lookup.get(("image", name))


def attach_media(
    messages_by_chat: dict[str, list[dict]],
    media_lookup: dict[tuple[str, str], dict],
    transcripts: list[dict],
    resolver: ResourceResolver | None = None,
    local_index: LocalFileIndex | None = None,
) -> dict[str, list[dict]]:
    transcript_map = {}
    for transcript in transcripts:
        text = transcript.get("text")
        if not text:
            continue
        key = (transcript.get("chat_username"), transcript.get("local_id"))
        transcript_map[key] = transcript

    enriched: dict[str, list[dict]] = {}
    for username, messages in messages_by_chat.items():
        enriched[username] = []
        for message in messages:
            item = dict(message)
            detail = _detail(message)
            message_type = int(message.get("type") or 0)
            attachment = None
            if message_type == IMAGE_TYPE:
                resource_md5 = (
                    resolver.md5(username, message.get("local_id"), IMAGE_TYPE)
                    if resolver
                    else None
                )
                md5 = resource_md5 or detail.get("md5") or _find_md5(
                    detail
                ) or _find_md5(message.get("content"))
                if md5:
                    key = str(md5).lower()
                    thumb = _image_record(media_lookup, username, key)
                    hd = _image_record(media_lookup, username, f"{key}_hd")
                    full = _image_record(media_lookup, username, f"{key}_full")
                else:
                    thumb = hd = full = None
                media = thumb or hd or full
                original = full or hd or thumb
                attachment = {
                    "kind": "image",
                    "url": media["url"] if media else None,
                    "original_url": original["url"] if original else None,
                    "width": detail.get("width"),
                    "height": detail.get("height"),
                }
            elif message_type == VIDEO_TYPE:
                resource_md5 = (
                    resolver.md5(username, message.get("local_id"), VIDEO_TYPE)
                    if resolver
                    else None
                )
                thumb = None
                if resource_md5:
                    thumb = media_lookup.get(
                        ("video_thumb", f"{resource_md5}_thumb")
                    )
                    if thumb is None:
                        for (kind, name), candidate in media_lookup.items():
                            if kind == "video_thumb" and name.startswith(resource_md5):
                                thumb = candidate
                                break
                size = detail.get("size")
                video = local_index.match_video(size) if local_index else None
                attachment = {
                    "kind": "video",
                    "duration": detail.get("duration_sec"),
                    "size": size,
                    "thumbnail": thumb["url"] if thumb else None,
                    "token": video.token if video else None,
                    "url": f"/api/local-file/{video.token}" if video else None,
                    "available": bool(video),
                    "name": video.name if video else None,
                }
            elif message_type == VOICE_TYPE:
                transcript = transcript_map.get((username, message.get("local_id"))) or {}
                attachment = {
                    "kind": "voice",
                    "duration": detail.get("duration_sec"),
                    "transcript": transcript.get("text"),
                    "model": transcript.get("model"),
                }
            elif (file_details := _file_details(message_type, message, detail)):
                category = category_for(file_details["name"])
                local = (
                    local_index.match(
                        file_details["name"],
                        file_details["size"],
                        _month_of(message),
                    )
                    if local_index
                    else None
                )
                attachment = {
                    "kind": "file",
                    "name": file_details["name"],
                    "size": file_details["size"],
                    "ext": file_details["ext"],
                    "category": category,
                    "previewable": is_previewable(category),
                    "token": local.token if local else None,
                    "url": f"/api/local-file/{local.token}" if local else None,
                    "local_path": local.absolute_path if local else None,
                    "available": bool(local),
                }
            item["media"] = attachment
            enriched[username].append(item)
    return enriched


def _image_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"GIF"):
        return "gif"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp"
    return None


def _export_avatar(
    username: str, head_images: dict[str, bytes], data_dir: Path
) -> str | None:
    buffer = head_images.get(username)
    if not isinstance(buffer, bytes) or not buffer:
        return None
    extension = _image_extension(buffer)
    if extension is None:
        return None
    filename = hashlib.sha1(username.encode("utf-8")).hexdigest()[:16] + "." + extension
    target = data_dir / "media" / "avatar" / filename
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not target.is_file() or target.stat().st_size != len(buffer):
        target.write_bytes(buffer)
        os.chmod(target, 0o600)
    return "/media/avatar/" + quote(filename, safe="")


def _display_name(contact: dict, fallback: str) -> str:
    return (
        contact.get("remark")
        or contact.get("nick_name")
        or fallback
        or contact.get("username")
        or ""
    )


def load_profiles(
    decrypted_dir: Path, data_dir: Path, conversations: list[dict]
) -> dict[str, dict]:
    """Read contact/group metadata and local avatar thumbnails."""
    decrypted_dir = Path(decrypted_dir).expanduser()
    profiles: dict[str, dict] = {}
    contact_rows: dict[str, dict] = {}
    rooms: dict[str, dict] = {}
    details: dict[str, dict] = {}
    member_counts: dict[int, int] = {}
    head_images: dict[str, bytes] = {}

    try:
        contact_db = decrypted_dir / "contact" / "contact.db"
        if contact_db.is_file():
            connection = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            try:
                for row in connection.execute(
                    "SELECT username, local_type, alias, remark, nick_name, "
                    "description, head_img_md5, chat_room_type FROM contact"
                ):
                    contact_rows[str(row["username"])] = dict(row)
                for row in connection.execute(
                    "SELECT id, username, owner FROM chat_room"
                ):
                    rooms[str(row["username"])] = dict(row)
                for row in connection.execute(
                    "SELECT room_id_, username_, announcement_, "
                    "announcement_editor_, announcement_publish_time_ "
                    "FROM chat_room_info_detail"
                ):
                    details[str(row["username_"])] = dict(row)
                for row in connection.execute(
                    "SELECT room_id, COUNT(*) AS n FROM chatroom_member "
                    "GROUP BY room_id"
                ):
                    member_counts[int(row["room_id"])] = int(row["n"])
            finally:
                connection.close()
    except sqlite3.Error as error:
        print(f"[sync] contact metadata unavailable: {error}", file=sys.stderr)

    try:
        head_db = decrypted_dir / "head_image" / "head_image.db"
        if head_db.is_file():
            connection = sqlite3.connect(f"file:{head_db}?mode=ro", uri=True)
            try:
                for username, image, _updated in connection.execute(
                    "SELECT username, image_buffer, update_time FROM head_image "
                    "ORDER BY update_time ASC"
                ):
                    if isinstance(image, bytes):
                        head_images[str(username)] = image
            finally:
                connection.close()
    except sqlite3.Error as error:
        print(f"[sync] head images unavailable: {error}", file=sys.stderr)

    for conversation in conversations:
        username = conversation["username"]
        contact = contact_rows.get(username, {})
        is_group = username.endswith("@chatroom")
        fallback_display = conversation.get("display_name") or username
        display = _display_name(contact, fallback_display)
        avatar_url = _export_avatar(username, head_images, data_dir)
        room = rooms.get(username, {})
        detail = details.get(username, {})
        owner = room.get("owner") or ""
        owner_display = ""
        if owner:
            owner_display = _display_name(contact_rows.get(owner, {}), owner)
        editor = detail.get("announcement_editor_") or ""
        editor_display = ""
        if editor:
            editor_display = _display_name(contact_rows.get(editor, {}), editor)
        profiles[username] = {
            "username": username,
            "display_name": display,
            "conversation_display": fallback_display,
            "kind": "group" if is_group else "contact",
            "remark": contact.get("remark") or "",
            "nick_name": contact.get("nick_name") or "",
            "alias": contact.get("alias") or "",
            "description": contact.get("description") or "",
            "avatar_url": avatar_url,
            "avatar_md5": contact.get("head_img_md5") or "",
            "tags": [],
            "member_count": member_counts.get(int(room["id"]))
            if room.get("id") is not None
            else None,
            "owner": owner,
            "owner_display": owner_display,
            "announcement": detail.get("announcement_") or "",
            "announcement_editor": editor,
            "announcement_editor_display": editor_display,
            "announcement_time": int(
                detail.get("announcement_publish_time_") or 0
            ),
        }
    return profiles


def build_snapshot(
    payload: dict,
    media_source: Path,
    data_dir: Path,
    resource_db: Path | None = None,
    decrypted_dir: Path | None = None,
    wechat_root: Path | None = None,
    local_index: LocalFileIndex | None = None,
) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(data_dir, 0o700)
    except OSError:
        pass
    if local_index is None:
        local_index = LocalFileIndex(discover_local_files(wechat_root))
    local_index.write(data_dir)
    media_records, lookup = prepare_media(
        list(payload.get("media", [])), media_source, data_dir
    )
    resolver = None
    if resource_db and Path(resource_db).is_file():
        try:
            resolver = ResourceResolver(Path(resource_db))
        except sqlite3.Error as error:
            print(f"[sync] resource db unavailable: {error}", file=sys.stderr)
    try:
        messages = attach_media(
            payload.get("messages_by_chat", {}),
            lookup,
            payload.get("transcripts", []),
            resolver,
            local_index,
        )
    finally:
        if resolver is not None:
            resolver.close()
    conversations = payload.get("conversations", [])
    profiles = (
        load_profiles(decrypted_dir, data_dir, conversations)
        if decrypted_dir
        else {}
    )
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conversations": conversations,
        "messages": messages,
        "media": media_records,
        "profiles": profiles,
        "counts": {
            "conversations": len(conversations),
            "messages": sum(len(items) for items in messages.values()),
            "media": len([item for item in media_records if item.get("url")]),
            "profiles": len(profiles),
            "local_files": len(local_index),
        },
    }


def write_snapshot(data_dir: Path, snapshot: dict) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = data_dir / "snapshot.json"
    temporary = data_dir / "snapshot.json.tmp"
    temporary.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return target


def run_once(
    host_api: str,
    data_dir: Path,
    media_source: Path,
    resource_db: Path | None = None,
    decrypted_dir: Path | None = None,
    wechat_root: Path | None = None,
) -> dict:
    local_index = LocalFileIndex(discover_local_files(wechat_root))
    with httpx.Client(timeout=20) as client:
        payload = fetch_all(client, host_api)
        register_local_files(client, host_api, local_index, wechat_root)
    snapshot = build_snapshot(
        payload,
        media_source,
        data_dir,
        resource_db,
        decrypted_dir,
        wechat_root,
        local_index,
    )
    write_snapshot(data_dir, snapshot)
    return snapshot["counts"]


def run_loop(
    host_api: str,
    data_dir: Path,
    media_source: Path,
    resource_db: Path | None,
    decrypted_dir: Path | None,
    outbox_dir: Path,
    interval: float,
    wechat_root: Path | None = None,
) -> int:
    send_worker = SendWorker(host_api, outbox_dir)
    send_worker.start()
    print(
        f"[send] worker started; outbox={outbox_dir}",
        flush=True,
    )
    action_worker = None
    if wechat_root:
        action_worker = FileActionWorker(wechat_root, outbox_dir)
        action_worker.start()
        print(
            f"[file-action] worker started; root={wechat_root}",
            flush=True,
        )
    try:
        while True:
            try:
                counts = run_once(
                    host_api,
                    data_dir,
                    media_source,
                    resource_db,
                    decrypted_dir,
                    wechat_root,
                )
                print(
                    f"[sync] conversations={counts['conversations']} "
                    f"messages={counts['messages']} media={counts['media']} "
                    f"profiles={counts.get('profiles', 0)} "
                    f"local_files={counts.get('local_files', 0)}",
                    flush=True,
                )
            except Exception as error:
                print(f"[sync] error: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            time.sleep(max(1.0, interval))
    except KeyboardInterrupt:
        send_worker.stop()
        if action_worker is not None:
            action_worker.stop()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-api", default=DEFAULT_HOST_API)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--media-source", type=Path, default=DEFAULT_MEDIA_SOURCE)
    parser.add_argument(
        "--decrypted-dir", type=Path, default=DEFAULT_DECRYPTED_DIR
    )
    parser.add_argument(
        "--resource-db",
        type=Path,
        default=DEFAULT_DECRYPTED_DIR / "message" / "message_resource.db",
    )
    parser.add_argument("--outbox-dir", type=Path, default=DEFAULT_OUTBOX_DIR)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument(
        "--wechat-root",
        type=Path,
        default=None,
        help="WeChat xwechat_files directory; defaults to auto-detect.",
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    wechat_root = args.wechat_root or default_wechat_root()
    if wechat_root:
        wechat_root = Path(wechat_root).expanduser()

    if args.once:
        try:
            counts = run_once(
                args.host_api,
                args.data_dir,
                args.media_source,
                args.resource_db,
                args.decrypted_dir,
                wechat_root,
            )
        except Exception as error:
            print(f"[sync] error: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
        print(json.dumps(counts, ensure_ascii=False))
        return 0
    return run_loop(
        args.host_api,
        args.data_dir,
        args.media_source,
        args.resource_db,
        args.decrypted_dir,
        args.outbox_dir,
        args.interval,
        wechat_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
