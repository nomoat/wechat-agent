import json

from fastapi.testclient import TestClient

from backend.app import create_app, resolve_media
from local_files import LocalFileEntry, LocalFileIndex, token_for


def make_data(tmp_path):
    data = tmp_path / "data"
    web = tmp_path / "web"
    data.mkdir()
    web.mkdir()
    (web / "index.html").write_text("<html>ok</html>")
    snapshot = {
        "updated_at": "2026-10-22T00:00:00+00:00",
        "conversations": [{"username": "lixianglong106", "display_name": "李翔龙"}],
        "messages": {},
        "media": [],
        "counts": {"conversations": 1, "messages": 0, "media": 0},
    }
    (data / "snapshot.json").write_text(json.dumps(snapshot))
    media = data / "media" / "image" / "2026-10" / "a.jpg"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"jpeg")
    return data, web


def test_state_health_media_and_index(tmp_path):
    data, web = make_data(tmp_path)
    client = TestClient(create_app(data, web))

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["conversations"][0]["username"] == "lixianglong106"

    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["counts"]["conversations"] == 1

    media = client.get("/media/image/2026-10/a.jpg")
    assert media.status_code == 200
    assert media.content == b"jpeg"

    index = client.get("/")
    assert index.status_code == 200
    assert "ok" in index.text


def test_media_traversal_is_rejected(tmp_path):
    data, web = make_data(tmp_path)
    (data / "secret.txt").write_text("secret")
    assert resolve_media(data, "../secret.txt") is None
    client = TestClient(create_app(data, web))
    assert client.get("/media/../secret.txt").status_code == 404


def test_missing_snapshot_returns_503(tmp_path):
    data = tmp_path / "empty"
    web = tmp_path / "web"
    data.mkdir()
    web.mkdir()
    client = TestClient(create_app(data, web))
    response = client.get("/api/state")
    assert response.status_code == 503
    health = client.get("/api/health").json()
    assert health["ok"] is False


def add_local_file(data, tmp_path, name, content, category):
    wechat = tmp_path / "wechat"
    target = wechat / "wxid_demo" / "msg" / "file" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    relative = target.relative_to(wechat).as_posix()
    entry = LocalFileEntry(
        token_for(relative), relative, name, len(content), 0, category
    )
    LocalFileIndex([entry]).write(data)
    return wechat, entry


def test_local_file_streams_range_and_queues_actions(tmp_path):
    data, web = make_data(tmp_path)
    outbox = tmp_path / "outbox"
    wechat, entry = add_local_file(
        data, tmp_path, "说明.txt", b"hello", "text"
    )
    client = TestClient(
        create_app(data, web, outbox, wechat_root=wechat)
    )

    response = client.get(f"/api/local-file/{entry.token}")
    assert response.status_code == 200
    assert response.content == b"hello"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"

    ranged = client.get(
        f"/api/local-file/{entry.token}", headers={"Range": "bytes=1-3"}
    )
    assert ranged.status_code == 206
    assert ranged.content == b"ell"
    assert ranged.headers["content-range"] == "bytes 1-3/5"

    download = client.get(
        f"/api/local-file/{entry.token}", params={"download": 1}
    )
    assert download.headers["content-disposition"].startswith("attachment")

    assert client.get("/api/local-file/" + "0" * 40).status_code == 404
    assert client.get("/api/local-file/not-a-token").status_code == 404

    queued = client.post(
        f"/api/local-file/{entry.token}/action", json={"action": "reveal"}
    )
    assert queued.status_code == 202
    request_id = queued.json()["request_id"]
    request = json.loads(
        (outbox / f"action-{request_id}.json").read_text()
    )
    assert request["relative_path"] == entry.relative_path
    assert request["action"] == "reveal"
    assert client.get(f"/api/file-action/{request_id}").json()["status"] == "pending"

    (outbox / f"action-result-{request_id}.json").write_text(
        json.dumps({"request_id": request_id, "action": "reveal", "status": "done"})
    )
    assert client.get(f"/api/file-action/{request_id}").json()["status"] == "done"
    assert client.post(
        f"/api/local-file/{entry.token}/action", json={"action": "delete"}
    ).status_code == 422
    assert client.get("/api/file-action/not-a-request").status_code == 404


def test_local_file_rejects_traversal_entries(tmp_path):
    data, web = make_data(tmp_path)
    (tmp_path / "secret.txt").write_text("secret")
    relative = "../secret.txt"
    entry = LocalFileEntry(
        token_for(relative), relative, "secret.txt", 6, 0, "text"
    )
    LocalFileIndex([entry]).write(data)
    wechat = tmp_path / "wechat"
    wechat.mkdir()
    client = TestClient(
        create_app(data, web, tmp_path / "outbox", wechat_root=wechat)
    )

    assert client.get(f"/api/local-file/{entry.token}").status_code == 404
    assert client.post(
        f"/api/local-file/{entry.token}/action", json={"action": "open"}
    ).status_code == 404


def test_send_outbox_flow(tmp_path):
    data, web = make_data(tmp_path)
    outbox = tmp_path / "outbox"
    client = TestClient(create_app(data, web, outbox))

    assert client.get("/api/config").json()["send_enabled"] is True

    response = client.post(
        "/api/send",
        json={
            "chat": "other@chatroom",
            "display_name": "另一个群",
            "text": "你好",
        },
    )
    assert response.status_code == 202
    request_id = response.json()["request_id"]
    requests = list(outbox.glob("request-*.json"))
    assert len(requests) == 1
    request = json.loads(requests[0].read_text())
    assert request["chat"] == "other@chatroom"
    assert request["display_name"] == "另一个群"

    pending = client.get(f"/api/send/{request_id}").json()
    assert pending["status"] == "pending"

    (outbox / f"result-{request_id}.json").write_text(
        json.dumps({"request_id": request_id, "status": "sent", "verified": True})
    )
    assert client.get(f"/api/send/{request_id}").json()["status"] == "sent"

    assert client.post(
        "/api/send",
        json={"chat": "other@chatroom", "display_name": "另一个群", "text": ""},
    ).status_code == 422
    assert client.post(
        "/api/send",
        json={"chat": "other@chatroom", "display_name": "另一个群", "text": "a\nb"},
    ).status_code == 422
    assert client.post(
        "/api/send", json={"chat": "other@chatroom", "text": "你好"}
    ).status_code == 422
    assert client.get("/api/send/not-a-request").status_code == 404
