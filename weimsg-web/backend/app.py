"""Read-only FastAPI service for the mirrored WeChat snapshot."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from local_files import LocalFileIndex, is_previewable, resolve_entry

REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
LOCAL_FILE_TOKEN_RE = re.compile(r"^[0-9a-f]{40}$")


class SendPayload(BaseModel):
    chat: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def single_line(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("message must be a single line without control characters")
        return value


def write_json_atomic(path: Path, payload: dict, mode: int = 0o644) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    os.chmod(temporary, mode)
    os.replace(temporary, path)


class FileActionPayload(BaseModel):
    action: Literal["open", "reveal"]


def resolve_media(data_dir: Path, relative: str) -> Path | None:
    base = (data_dir / "media").resolve()
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target if target.is_file() else None


def create_app(
    data_dir: Path | None = None,
    web_dir: Path | None = None,
    outbox_dir: Path | None = None,
    wechat_root: Path | None = None,
) -> FastAPI:
    data_dir = Path(data_dir or os.getenv("DATA_DIR", "/data")).expanduser()
    web_dir = Path(
        web_dir or Path(__file__).resolve().parents[1] / "web"
    ).expanduser()
    outbox_dir = Path(
        outbox_dir or os.getenv("OUTBOX_DIR", "/outbox")
    ).expanduser()
    wechat_root = Path(
        wechat_root or os.getenv("WECHAT_FILES_ROOT", "/wechat-files")
    ).expanduser()
    app = FastAPI(
        title="WeMsg Web",
        version="0.1.0",
        description="Read-only WeChat dashboard over a local snapshot.",
    )

    @app.get("/api/state")
    def state():
        path = data_dir / "snapshot.json"
        if not path.is_file():
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "snapshot_missing",
                    "message": "snapshot.json not found; run make sync on the host",
                },
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(
                status_code=503,
                detail={"code": "snapshot_invalid", "message": str(error)},
            ) from error
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health() -> dict:
        path = data_dir / "snapshot.json"
        if not path.is_file():
            return {
                "ok": False,
                "snapshot_available": False,
                "data_dir": str(data_dir),
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            age = max(0.0, time.time() - path.stat().st_mtime)
        except (OSError, json.JSONDecodeError) as error:
            return {
                "ok": False,
                "snapshot_available": True,
                "error": str(error),
            }
        return {
            "ok": True,
            "snapshot_available": True,
            "updated_at": payload.get("updated_at"),
            "age_sec": round(age, 1),
            "counts": payload.get("counts", {}),
        }

    @app.get("/api/config")
    def config() -> dict:
        return {"send_enabled": True}

    @app.post("/api/send", status_code=202)
    def send(payload: SendPayload) -> dict:
        chat = payload.chat.strip()
        display_name = payload.display_name.strip()
        text = payload.text.strip()
        if not chat or not display_name or not text:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "empty_field",
                    "message": "chat, display_name and text are required",
                },
            )
        request_id = uuid.uuid4().hex
        request = {
            "id": request_id,
            "chat": chat,
            "display_name": display_name,
            "text": text,
            "created_at": time.time(),
        }
        outbox_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json_atomic(outbox_dir / f"request-{request_id}.json", request)
        return {"request_id": request_id, "status": "queued"}

    @app.get("/api/send/{request_id}")
    def send_status(request_id: str) -> dict:
        if not REQUEST_ID_RE.fullmatch(request_id):
            raise HTTPException(status_code=404, detail="send request not found")
        result = outbox_dir / f"result-{request_id}.json"
        if result.is_file():
            try:
                return json.loads(result.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise HTTPException(
                    status_code=500,
                    detail={"code": "result_invalid", "message": str(error)},
                ) from error
        return {"request_id": request_id, "status": "pending"}

    def local_entry(token: str):
        index = LocalFileIndex.load(data_dir)
        entry = index.get(token)
        if entry is None:
            return None, None
        return entry, resolve_entry(wechat_root, entry)

    @app.get("/api/local-file/{token}")
    def local_file(token: str, download: int = 0):
        if not LOCAL_FILE_TOKEN_RE.fullmatch(token):
            raise HTTPException(status_code=404, detail="local file not found")
        entry, target = local_entry(token)
        if entry is None or target is None:
            raise HTTPException(status_code=404, detail="local file not found")
        media_type = mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
        disposition = (
            "attachment"
            if download or not is_previewable(entry.category)
            else "inline"
        )
        return FileResponse(
            target,
            media_type=media_type,
            filename=entry.name,
            content_disposition_type=disposition,
            headers={
                "Cache-Control": "private, max-age=60",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/api/local-file/{token}/action", status_code=202)
    def local_file_action(token: str, payload: FileActionPayload) -> dict:
        if not LOCAL_FILE_TOKEN_RE.fullmatch(token):
            raise HTTPException(status_code=404, detail="local file not found")
        entry, target = local_entry(token)
        if entry is None or target is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "local_file_missing",
                    "message": "file is not available in WeChat's local save path",
                },
            )
        request_id = uuid.uuid4().hex
        outbox_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json_atomic(
            outbox_dir / f"action-{request_id}.json",
            {
                "id": request_id,
                "action": payload.action,
                "token": token,
                "relative_path": entry.relative_path,
                "created_at": time.time(),
            },
        )
        return {"request_id": request_id, "status": "queued"}

    @app.get("/api/file-action/{request_id}")
    def file_action_status(request_id: str) -> dict:
        if not REQUEST_ID_RE.fullmatch(request_id):
            raise HTTPException(status_code=404, detail="file action not found")
        result = outbox_dir / f"action-result-{request_id}.json"
        if result.is_file():
            try:
                return json.loads(result.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise HTTPException(
                    status_code=500,
                    detail={"code": "action_result_invalid", "message": str(error)},
                ) from error
        return {"request_id": request_id, "status": "pending"}

    @app.get("/media/{path:path}")
    def media(path: str):
        target = resolve_media(data_dir, path)
        if target is None:
            raise HTTPException(status_code=404, detail="media not found")
        return FileResponse(
            target, headers={"Cache-Control": "public, max-age=60"}
        )

    if web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/")
        def index():
            return FileResponse(web_dir / "index.html")

    return app


app = create_app()
