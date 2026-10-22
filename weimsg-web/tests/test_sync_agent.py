import json

from local_files import (
    LocalFileEntry,
    LocalFileIndex,
    category_for,
    discover_local_files,
    token_for,
)
from sync_agent import (
    FileActionWorker,
    build_snapshot,
    default_wechat_root,
    write_snapshot,
)


def test_image_is_mapped_by_md5_and_copied(tmp_path):
    media_source = tmp_path / "media-source"
    media_source.mkdir()
    image = media_source / "abc.jpg"
    image.write_bytes(b"jpeg")
    md5 = "a" * 32
    payload = {
        "conversations": [{"username": "lixianglong106", "display_name": "李翔龙"}],
        "messages_by_chat": {
            "lixianglong106": [
                {
                    "local_id": 1,
                    "type": 3,
                    "type_name": "图片",
                    "content": "[图片]",
                    "detail_json": json.dumps({"md5": md5, "width": 10, "height": 20}),
                }
            ]
        },
        "media": [
            {
                "kind": "image",
                "chat_username": "lixianglong106",
                "month": "2026-10",
                "name": md5,
                "decoded_path": str(image),
                "format": "jpg",
                "size": 4,
            }
        ],
        "transcripts": [],
    }

    snapshot = build_snapshot(payload, media_source, tmp_path / "web-data")

    message = snapshot["messages"]["lixianglong106"][0]
    assert message["media"]["kind"] == "image"
    assert message["media"]["url"].endswith(f"{md5}.jpg")
    copied = tmp_path / "web-data" / "media" / "image" / "2026-10" / f"{md5}.jpg"
    assert copied.read_bytes() == b"jpeg"


def test_image_preview_prefers_full_original(tmp_path):
    media_source = tmp_path / "media-source"
    media_source.mkdir()
    thumb = media_source / "thumb.jpg"
    full = media_source / "full.jpg"
    thumb.write_bytes(b"thumb")
    full.write_bytes(b"original")
    md5 = "c" * 32
    payload = {
        "conversations": [{"username": "chat", "display_name": "会话"}],
        "messages_by_chat": {
            "chat": [
                {
                    "local_id": 1,
                    "type": 3,
                    "type_name": "图片",
                    "content": "[图片]",
                    "detail_json": json.dumps({"md5": md5}),
                }
            ]
        },
        "media": [
            {
                "kind": "image",
                "chat_username": "chat",
                "month": "2026-10",
                "name": md5,
                "decoded_path": str(thumb),
                "format": "jpg",
                "size": 5,
            },
            {
                "kind": "image",
                "chat_username": "chat",
                "month": "2026-10",
                "name": f"{md5}_full",
                "decoded_path": str(full),
                "format": "jpg",
                "size": 8,
            },
        ],
        "transcripts": [],
    }

    snapshot = build_snapshot(payload, media_source, tmp_path / "web-data")

    media = snapshot["messages"]["chat"][0]["media"]
    assert media["url"].endswith(f"{md5}.jpg")
    assert media["original_url"].endswith(f"{md5}_full.jpg")


def test_video_and_voice_metadata(tmp_path):
    payload = {
        "conversations": [{"username": "chat", "display_name": "群聊"}],
        "messages_by_chat": {
            "chat": [
                {
                    "local_id": 1,
                    "type": 43,
                    "type_name": "视频",
                    "content": "[视频 1分]",
                    "detail_json": json.dumps({"duration_sec": 60, "size": 123}),
                },
                {
                    "local_id": 2,
                    "type": 34,
                    "type_name": "语音",
                    "content": "[语音]",
                    "detail_json": json.dumps({"duration_sec": 8}),
                },
            ]
        },
        "media": [],
        "transcripts": [
            {"chat_username": "chat", "local_id": 2, "text": "周五见", "model": "gemini"}
        ],
    }

    snapshot = build_snapshot(payload, tmp_path / "media", tmp_path / "web-data")

    video, voice = snapshot["messages"]["chat"]
    assert video["media"]["kind"] == "video"
    assert video["media"]["duration"] == 60
    assert voice["media"]["kind"] == "voice"
    assert voice["media"]["transcript"] == "周五见"


def test_write_snapshot_is_atomic_and_private(tmp_path):
    target = write_snapshot(tmp_path / "data", {"counts": {"messages": 1}})
    assert target.is_file()
    assert json.loads(target.read_text())["counts"]["messages"] == 1
    assert (target.stat().st_mode & 0o777) == 0o600


def test_resource_md5_maps_image_and_video_thumbnail(tmp_path):
    import sqlite3

    resource_db = tmp_path / "message_resource.db"
    connection = sqlite3.connect(resource_db)
    connection.execute("CREATE TABLE ChatName2Id (user_name TEXT)")
    connection.execute("INSERT INTO ChatName2Id(rowid, user_name) VALUES (1, 'chat')")
    connection.execute(
        "CREATE TABLE MessageResourceInfo (chat_id INTEGER, message_local_id INTEGER, "
        "message_local_type INTEGER, message_create_time INTEGER, packed_info BLOB)"
    )
    image_md5 = "b" * 32
    video_md5 = "c" * 32
    marker = b"\x12\x22\x0a\x20"
    connection.execute(
        "INSERT INTO MessageResourceInfo VALUES (1, 1, 3, 100, ?)",
        (marker + image_md5.encode() + b"tail",),
    )
    connection.execute(
        "INSERT INTO MessageResourceInfo VALUES (1, 2, 43, 101, ?)",
        (marker + video_md5.encode() + b"tail",),
    )
    connection.commit()
    connection.close()

    media_source = tmp_path / "media-source"
    media_source.mkdir()
    (media_source / "b.jpg").write_bytes(b"image")
    (media_source / "c_thumb.jpg").write_bytes(b"thumb")
    payload = {
        "conversations": [{"username": "chat", "display_name": "群聊"}],
        "messages_by_chat": {
            "chat": [
                {"local_id": 1, "type": 3, "content": "[图片]", "detail_json": "{}"},
                {
                    "local_id": 2,
                    "type": 43,
                    "content": "[视频]",
                    "detail_json": json.dumps({"duration_sec": 60, "size": 10}),
                },
            ]
        },
        "media": [
            {
                "kind": "image",
                "chat_username": "chat",
                "month": "2026-10",
                "name": image_md5,
                "decoded_path": str(media_source / "b.jpg"),
                "format": "jpg",
                "size": 5,
            },
            {
                "kind": "video_thumb",
                "chat_username": None,
                "month": "2026-10",
                "name": f"{video_md5}_thumb",
                "decoded_path": str(media_source / "c_thumb.jpg"),
                "format": "jpg",
                "size": 5,
            },
        ],
        "transcripts": [],
    }

    snapshot = build_snapshot(
        payload, media_source, tmp_path / "web-data", resource_db
    )

    image, video = snapshot["messages"]["chat"]
    assert image["media"]["url"].endswith(f"{image_md5}.jpg")
    assert video["media"]["thumbnail"].endswith(f"{video_md5}_thumb.jpg")


def test_send_worker_processes_outbox(tmp_path, monkeypatch):
    from sync_agent import SendWorker

    outbox = tmp_path / "outbox"
    outbox.mkdir()
    request_id = "a" * 32
    (outbox / f"request-{request_id}.json").write_text(
        json.dumps(
            {
                "id": request_id,
                "chat": "other@chatroom",
                "display_name": "另一个群",
                "text": "你好",
            }
        )
    )
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "request_id": request_id,
                "sent": True,
                "verified": True,
                "text": "你好",
            }

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return FakeResponse()

    monkeypatch.setattr("sync_agent.httpx.post", fake_post)
    worker = SendWorker("http://127.0.0.1:8769", outbox)
    worker.process_once()

    result = json.loads((outbox / f"result-{request_id}.json").read_text())
    assert result["status"] == "sent"
    assert result["verified"] is True
    assert calls[0][1]["request_id"] == request_id
    assert calls[0][1]["chat"] == "other@chatroom"
    assert calls[0][1]["display_name"] == "另一个群"
    assert not (outbox / f"request-{request_id}.json").exists()


def test_send_worker_rejects_missing_display_name(tmp_path, monkeypatch):
    from sync_agent import SendWorker

    outbox = tmp_path / "outbox"
    outbox.mkdir()
    request_id = "b" * 32
    (outbox / f"request-{request_id}.json").write_text(
        json.dumps({"id": request_id, "chat": "someone-else", "text": "你好"})
    )

    def fail_post(*args, **kwargs):
        raise AssertionError("must not call the host send endpoint")

    monkeypatch.setattr("sync_agent.httpx.post", fail_post)
    worker = SendWorker("http://127.0.0.1:8769", outbox)
    worker.process_once()

    result = json.loads((outbox / f"result-{request_id}.json").read_text())
    assert result["status"] == "failed"
    assert result["error"] == "recipient_or_text_rejected"


def test_profiles_and_local_avatars(tmp_path):
    import sqlite3

    decrypted = tmp_path / "decrypted"
    contact_dir = decrypted / "contact"
    head_dir = decrypted / "head_image"
    contact_dir.mkdir(parents=True)
    head_dir.mkdir(parents=True)

    contact = sqlite3.connect(contact_dir / "contact.db")
    contact.execute(
        "CREATE TABLE contact (id INTEGER, username TEXT, local_type INTEGER, "
        "alias TEXT, remark TEXT, nick_name TEXT, description TEXT, "
        "head_img_md5 TEXT, chat_room_type INTEGER)"
    )
    contact.execute(
        "INSERT INTO contact VALUES (1,'lixianglong106',1,'lixianglong1205',"
        "'李翔龙备注','李翔龙','这是备忘', 'abc',0)"
    )
    contact.execute(
        "INSERT INTO contact VALUES (2,'123@chatroom',2,'','','测试群','', 'def',0)"
    )
    contact.execute("CREATE TABLE chat_room (id INTEGER, username TEXT, owner TEXT)")
    contact.execute("INSERT INTO chat_room VALUES (1,'123@chatroom','lixianglong106')")
    contact.execute(
        "CREATE TABLE chat_room_info_detail (room_id_ INTEGER, username_ TEXT, "
        "announcement_ TEXT, announcement_editor_ TEXT, "
        "announcement_publish_time_ INTEGER)"
    )
    contact.execute(
        "INSERT INTO chat_room_info_detail VALUES "
        "(1,'123@chatroom','群公告内容','lixianglong106',1792591200)"
    )
    contact.execute("CREATE TABLE chatroom_member (room_id INTEGER, member_id INTEGER)")
    contact.executemany(
        "INSERT INTO chatroom_member VALUES (1, ?)", [(1,), (2,), (3,)]
    )
    contact.commit()
    contact.close()

    heads = sqlite3.connect(head_dir / "head_image.db")
    heads.execute(
        "CREATE TABLE head_image (username TEXT, md5 TEXT, "
        "image_buffer BLOB, update_time INTEGER)"
    )
    heads.executemany(
        "INSERT INTO head_image VALUES (?, ?, ?, ?)",
        [
            ("lixianglong106", "a", b"\xff\xd8\xff\xe0" + b"x" * 12, 1),
            ("123@chatroom", "b", b"\xff\xd8\xff\xe0" + b"y" * 12, 2),
        ],
    )
    heads.commit()
    heads.close()

    payload = {
        "conversations": [
            {"username": "lixianglong106", "display_name": "李翔龙"},
            {"username": "123@chatroom", "display_name": "测试群"},
        ],
        "messages_by_chat": {"lixianglong106": [], "123@chatroom": []},
        "media": [],
        "transcripts": [],
    }
    snapshot = build_snapshot(
        payload, tmp_path / "media-source", tmp_path / "web-data", None, decrypted
    )

    profile = snapshot["profiles"]["lixianglong106"]
    assert profile["kind"] == "contact"
    assert profile["remark"] == "李翔龙备注"
    assert profile["nick_name"] == "李翔龙"
    assert profile["alias"] == "lixianglong1205"
    assert profile["description"] == "这是备忘"
    assert profile["avatar_url"].startswith("/media/avatar/")
    assert snapshot["counts"]["profiles"] == 2
    avatar_file = tmp_path / "web-data" / profile["avatar_url"].lstrip("/")
    assert avatar_file.is_file()

    group = snapshot["profiles"]["123@chatroom"]
    assert group["kind"] == "group"
    assert group["member_count"] == 3
    assert group["announcement"] == "群公告内容"
    assert group["owner_display"] == "李翔龙备注"


def _file_payload(name, size, message_type=25769803825, subtype=6):
    return {
        "conversations": [{"username": "chat", "display_name": "群聊"}],
        "messages_by_chat": {
            "chat": [
                {
                    "local_id": 1,
                    "type": message_type,
                    "subtype": subtype,
                    "type_name": "文件",
                    "content": f"[文件] {name}",
                    "detail_json": json.dumps(
                        {
                            "title": name,
                            "size_bytes": size,
                            "ext": name.rsplit(".", 1)[-1].lower(),
                        }
                    ),
                }
            ]
        },
        "media": [],
        "transcripts": [],
    }


def test_local_video_is_attached_by_size_from_wechat_path(tmp_path):
    root = tmp_path / "xwechat_files"
    source = root / "wxid_demo" / "msg" / "video" / "2026-10" / "cached.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"v" * 123)
    payload = {
        "conversations": [{"username": "chat", "display_name": "群聊"}],
        "messages_by_chat": {
            "chat": [
                {
                    "local_id": 1,
                    "type": 43,
                    "type_name": "视频",
                    "content": "[视频]",
                    "detail_json": json.dumps(
                        {"duration_sec": 27, "size": 123}
                    ),
                }
            ]
        },
        "media": [],
        "transcripts": [],
    }

    snapshot = build_snapshot(
        payload,
        tmp_path / "media",
        tmp_path / "web-data",
        wechat_root=root,
    )

    video = snapshot["messages"]["chat"][0]
    token = token_for("wxid_demo/msg/video/2026-10/cached.mp4")
    assert video["media"]["url"] == f"/api/local-file/{token}"
    assert video["media"]["available"] is True
    assert not (tmp_path / "web-data" / "media" / "video").exists()
    index = json.loads((tmp_path / "web-data" / "local-files.json").read_text())
    assert index["files"][token]["relative_path"].endswith("cached.mp4")


def test_video_size_mismatch_stays_unavailable(tmp_path):
    root = tmp_path / "xwechat_files"
    source = root / "wxid_demo" / "msg" / "video" / "other.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"v" * 10)

    snapshot = build_snapshot(
        _file_payload("报表.xlsx", 0) | {
            "messages_by_chat": {
                "chat": [
                    {
                        "local_id": 1,
                        "type": 43,
                        "content": "[视频]",
                        "detail_json": json.dumps(
                            {"duration_sec": 27, "size": 11}
                        ),
                    }
                ]
            }
        },
        tmp_path / "media",
        tmp_path / "web-data",
        wechat_root=root,
    )

    assert snapshot["messages"]["chat"][0]["media"]["url"] is None


def test_file_message_attaches_local_file_by_name_and_size(tmp_path):
    root = tmp_path / "xwechat_files"
    source = root / "wxid_demo" / "msg" / "file" / "2026-10" / "报表(2).xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x" * 1234)

    snapshot = build_snapshot(
        _file_payload("报表(2).xlsx", 1234),
        tmp_path / "media",
        tmp_path / "web-data",
        wechat_root=root,
    )

    media = snapshot["messages"]["chat"][0]["media"]
    token = token_for("wxid_demo/msg/file/2026-10/报表(2).xlsx")
    assert media == {
        "kind": "file",
        "name": "报表(2).xlsx",
        "size": 1234,
        "ext": "xlsx",
        "category": "office",
        "previewable": False,
        "token": token,
        "url": f"/api/local-file/{token}",
        "local_path": str(source.resolve()),
        "available": True,
    }
    assert snapshot["counts"]["local_files"] == 1


def test_local_file_index_is_persisted_to_duckdb_api(tmp_path):
    import httpx

    from sync_agent import register_local_files

    root = tmp_path / "xwechat_files"
    source = root / "wxid_demo" / "msg" / "file" / "2026-10" / "报表.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x" * 12)
    index = LocalFileIndex(discover_local_files(root))
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"count": 1})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        register_local_files(client, "http://127.0.0.1:8769", index, root)

    assert captured["body"]["root"] == str(root.resolve())
    record = captured["body"]["files"][0]
    assert record["relative_path"] == "wxid_demo/msg/file/2026-10/报表.xlsx"
    assert record["absolute_path"] == str(source.resolve())
    assert record["category"] == "office"


def test_file_message_without_local_copy_is_unavailable(tmp_path):
    snapshot = build_snapshot(
        _file_payload("缺失.pdf", 99),
        tmp_path / "media",
        tmp_path / "web-data",
        wechat_root=tmp_path / "empty-root",
    )

    media = snapshot["messages"]["chat"][0]["media"]
    assert media["kind"] == "file"
    assert media["available"] is False
    assert media["url"] is None
    assert media["token"] is None


def test_duplicate_file_uses_exact_name(tmp_path):
    root = tmp_path / "xwechat_files"
    folder = root / "wxid_demo" / "msg" / "file" / "2026-10"
    folder.mkdir(parents=True)
    (folder / "改.rar").write_bytes(b"a" * 20)
    (folder / "改(1).rar").write_bytes(b"b" * 20)

    snapshot = build_snapshot(
        _file_payload("改.rar", 20),
        tmp_path / "media",
        tmp_path / "web-data",
        wechat_root=root,
    )

    media = snapshot["messages"]["chat"][0]["media"]
    assert media["name"] == "改.rar"
    assert media["available"] is True
    assert media["token"] == token_for("wxid_demo/msg/file/2026-10/改.rar")


def test_discover_local_files_skips_thumbnails_and_partials(tmp_path):
    root = tmp_path / "xwechat_files"
    account = root / "wxid_demo"
    file_dir = account / "msg" / "file" / "2026-10"
    video_dir = account / "msg" / "video" / "2026-10"
    file_dir.mkdir(parents=True)
    video_dir.mkdir(parents=True)
    (file_dir / "报告.docx").write_bytes(b"d" * 5)
    (file_dir / "下载中.tmp").write_bytes(b"t" * 5)
    (file_dir / "空.txt").write_bytes(b"")
    (video_dir / "clip.mp4").write_bytes(b"v" * 5)
    (video_dir / "clip_thumb.jpg").write_bytes(b"j" * 5)
    (video_dir / ("a" * 32)).write_bytes(b"v" * 7)

    records = discover_local_files(root)
    records_again = discover_local_files(root)

    names = sorted(record.name for record in records)
    assert names == sorted(["报告.docx", "clip.mp4", "a" * 32])
    assert [record.token for record in records] == [
        record.token for record in records_again
    ]
    assert category_for("报告.docx") == "office"
    assert category_for("clip.mp4") == "video"
    assert category_for("a" * 32) == "other"


def test_local_file_index_matching_rules(tmp_path):
    entries = [
        LocalFileEntry("a" * 40, "wxid/msg/file/2026-10/改.rar", "改.rar", 20, 0, "archive"),
        LocalFileEntry("b" * 40, "wxid/msg/file/2026-11/改(1).rar", "改(1).rar", 20, 0, "archive"),
        LocalFileEntry("c" * 40, "wxid/msg/file/2026-10/报表.xlsx", "报表.xlsx", 30, 0, "office"),
    ]
    index = LocalFileIndex(entries)

    assert index.match("改.rar", 20).token == "a" * 40
    assert index.match("改.rar", 20, month="2026-11").token == "a" * 40
    assert index.match("改.rar", 20).name == "改.rar"
    assert index.match("报表(2).xlsx", 30).token == "c" * 40
    assert index.match("未知.rar", 20) is None
    assert index.match_video(20) is None


def test_default_wechat_root_reads_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_FILES_ROOT", str(tmp_path))
    assert default_wechat_root() == tmp_path


def test_file_action_worker_opens_and_reveals(tmp_path, monkeypatch):
    root = tmp_path / "xwechat_files"
    target = root / "wxid_demo" / "msg" / "file" / "报告.docx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"d")
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    commands = []

    class Completed:
        returncode = 0
        stderr = b""

    def fake_run(command, **kwargs):
        commands.append(command)
        return Completed()

    monkeypatch.setattr("sync_agent.subprocess.run", fake_run)
    worker = FileActionWorker(root, outbox)
    for request_id, action in (("1" * 32, "open"), ("2" * 32, "reveal")):
        (outbox / f"action-{request_id}.json").write_text(
            json.dumps(
                {
                    "id": request_id,
                    "action": action,
                    "relative_path": "wxid_demo/msg/file/报告.docx",
                }
            )
        )
    worker.process_once()

    assert commands[0] == ["open", str(target.resolve())]
    assert commands[1] == ["open", "-R", str(target.resolve())]
    for request_id in ("1" * 32, "2" * 32):
        result = json.loads(
            (outbox / f"action-result-{request_id}.json").read_text()
        )
        assert result["status"] == "done"

    (outbox / f"action-{'3' * 32}.json").write_text(
        json.dumps(
            {
                "id": "3" * 32,
                "action": "open",
                "relative_path": "../outside.txt",
            }
        )
    )
    worker.process_once()
    result = json.loads(
        (outbox / f"action-result-{'3' * 32}.json").read_text()
    )
    assert result["status"] == "failed"
    assert result["error"] == "file_not_found"
