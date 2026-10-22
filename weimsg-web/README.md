# WeMsg Web

仿微信 UI 的微信消息实时看板，默认支持向任意会话发送消息。消息元数据来自本机 `wechat-agent` 服务的 DuckDB 归档；图片、视频、压缩包、Word/Excel/PDF 等附件不再从 DuckDB 取字节，而是由宿主机索引微信 PC 端本地保存目录，Docker 只读挂载后按 token 直接流式返回。文件附件的本机绝对路径会写入 DuckDB `local_files` 表，并随快照提供给 Electron 快速定位。Web 服务在 Docker 中运行，Electron 线上版加载 Docker 页面。发送请求由宿主机 `sync_agent` 消费，最终调用宿主机 `/send` 的微信 UI 自动化完成。

## 架构

```text
官方微信 → 宿主机 DBSync（3s 解密）→ DuckDB（含 local_files 绝对路径）
                                    ↓ 宿主机 sync_agent（3s）
                         web-data/snapshot.json + local-files.json
                                    ↓ Docker 只读挂载
微信 PC 本地保存目录 ──只读挂载──→ FastAPI + 静态 Web UI ← Electron
                                    ↓
                         /api/local-file/<token> 流式返回文件
```

详见 [DESIGN.md](DESIGN.md)。

## 前置条件

1. 宿主机已部署并运行 `wechat-agent` 的 `integration` 实时服务（该模块未随本仓库公开）：
   - `http://127.0.0.1:8769/health` 可访问
   - `/db/stats` 有数据
   - `WECHAT_DB_SYNC_INTERVAL=3`
2. 已安装 `uv`、Docker Desktop、Node.js（仅 Electron 打包需要）、`ffmpeg`（用于把微信 `wxgf` 原图转成 JPEG；`brew install ffmpeg`）。

## 本地运行

```sh
cd weimsg-web
uv sync

# 1) 宿主机同步快照（每 3 秒；前台运行）
make sync

# 另一个终端：Docker 启动 Web
make build
make up

# 打开 http://127.0.0.1:8080
```

只生成一次快照：

```sh
make sync-once
```

## Web UI

- 左侧：会话列表（群聊/联系人、真实头像、最后一条消息、时间、未读计数）
- 右侧：消息窗口（文本/图片/视频/语音/系统消息）
- 右侧资料面板：头像、备注、昵称、微信号、标签、备忘/描述；群聊额外显示公告、成员数、群主
- 宽屏默认显示资料面板，窄屏通过“资料”按钮打开/关闭；无标签时显示“暂无标签”
- 每 3 秒轮询 `/api/state`
- 图片消息内联显示缩略图，点击后优先加载同目录的 `_full.jpg` 原图；`wxgf` 原图由宿主机 `ffmpeg` 转码，浏览器不再只看到 157×210 缩略图
- 动画 GIF/WebP/APNG 按原格式保存，不经过 `wxgf` 转码；当前 25 条图片消息全部为静态 JPEG/PNG，浏览器 `ImageDecoder` 逐张确认 `frameCount=1`
- 视频显示缩略图 + 时长/大小卡片，点击打开仿微信播放弹层
- 文件消息显示文件卡片（按扩展名区分图片/视频/音频/PDF/文本/Office/压缩包图标），标注文件大小；本地没有副本时显示“本地未找到”并禁用操作
- 文件卡片点击行为：图片放大、视频播放、音频/PDF/纯文本页内预览、Office/压缩包/其他调用宿主机默认应用打开
- 每张文件卡片提供“打开”“打开位置”：通过 `/api/local-file/<token>/action` 写入 outbox，宿主机 `FileActionWorker` 执行 macOS `open` / `open -R`
- 文件字节由 Docker 只读挂载的微信 PC 本地保存目录直接返回（支持 HTTP Range），不经过 DuckDB，也不复制到 `web-data`
- 文件消息的绝对路径同时写入 DuckDB `local_files` 表和快照 `media.local_path`，Electron 可直接定位；流式读取仍只接受 token
- 文本中的微信表情 token（如 `[破涕为笑]`）渲染为 Unicode 表情；引用回复在气泡内显示“发送者：摘要”灰色引用块 + 分隔线 + 正文
- 点击引用块会像 PC 微信一样滚动到原消息并短暂高亮；原消息不在当前同步范围时给出提示
- 视频优先播放本地已缓存的完整文件；未缓存时弹层显示缩略图和“原视频尚未缓存到本地”，并提供“重新检测”
- 默认允许向任意会话发送；宿主机发送前会定位并核对会话
- 发送流程：页面输入 → `/api/send` → `web-outbox` → 宿主机 `SendWorker` → `/send` → 微信 UI 自动化
- 可选白名单：宿主机设置 `WECHAT_ALLOW_ANY_RECIPIENT=false` + `WECHAT_TARGET_CHAT` 后只允许指定联系人

## Docker

```sh
make build      # docker compose build
make up         # docker compose up -d
make logs       # 查看日志
make down       # 停止
make restart    # 重启
```

`docker-compose.yml` 把 `./web-data` 只读挂载到 `/data`、`./web-outbox` 挂载到 `/outbox`，并把微信 PC 的 `xwechat_files` 目录只读挂载到 `/wechat-files`。默认路径为 `~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files`；可用 `WECHAT_FILES_HOST_DIR=/your/path make up` 覆盖。

Dockerfile 基于 `python:3.12-slim`，镜像内安装 `ffmpeg`（`apt-get install --no-install-recommends ffmpeg`）。实测镜像内 `ffmpeg 7.1.5`、`/usr/bin/ffprobe` 可用，`ffmpeg -decoders` 含 `hevc`；用真实 `508c...wxgf` 按生产参数（`-f hevc -frames:v 1 -c:v mjpeg -q:v 2`）在容器内转码得到 1280×1706 JPEG（325,740 字节）。

## Electron（线上环境）

```sh
cd electron
npm install

# 本地调试：加载本机 Docker Web
WEB_UI_URL=http://127.0.0.1:8080 npm start

# 线上打包：加载已部署的 Web URL
WEB_UI_URL=https://your-domain.example.com npm run build
```

打包后的应用启动时加载 `WEB_UI_URL`；未设置时默认 `http://127.0.0.1:8080`。

## 测试

```sh
uv run pytest
```

覆盖：快照构建、联系人/群资料与头像导出、图片 md5 关联、`message_resource.db` 缩略图 md5 关联、原图/缩略图分离与 `original_url` 优先级、动画 GIF 原格式保留、媒体复制（只读目标可重建）、语音/视频元数据、微信本地文件发现与 token 索引、文件消息按名称+大小匹配（含重名、缺失、同名不同月份）、视频按字节大小匹配本地路径、`local-files.json` 权限、绝对路径写入 DuckDB `/db/local-files`、本地文件 HTTP 流式返回/Range/Content-Disposition/目录穿越防护、文件操作 outbox 与宿主 worker（`open` / `open -R` / 越界路径拒绝）、表情/引用解析与引用跳转定位（Node `node:test`，由 pytest 调起；跳转按 `server_id` 精确匹配，缺失时回退发送者/时间/类型；文件扩展名分类、图片放大原图选择）、后端 API、发送 outbox、收件人透传/可选白名单、缺少快照时的 503、Docker 镜像包含 `ffmpeg`。

当前结果：`26 passed`（其中 1 条为 Node 前端单测入口，内含 11 个 `node:test` 用例）。上游 `integration`：`62 passed`。测试依赖使用 `httpx2`，Starlette `TestClient` 不再出现 `httpx` 弃用警告。

## 实测（2026-10-22）

- Docker 镜像重建成功（`weimsg-web:local`，844 MB），容器 `healthy`；`http://127.0.0.1:8080` 返回 200。容器内 `ffmpeg 7.1.5` / `ffprobe` 可用且支持 HEVC，真实 `wxgf` 转码验证通过（见上）
- 重建后的容器再次逐 URL 拉取全部图片：25 条图片消息、26 个唯一 URL 全部 200，25 个 `image/jpeg` + 1 个 `image/png`，0 失败
- 快照：10 会话 / 257 消息 / 39 媒体 / 10 份会话资料；DuckDB `local_files` 6 条（5 份文档/压缩包 + 1 个完整视频），均带绝对路径
- Playwright 真实页面验证：
  - 左侧 10 个群聊/联系人，头像是真实微信头像（无头像回退首字色块）
  - 资料面板：联系人显示备注/昵称/微信号/标签/备忘；群聊显示公告、成员数、群主
  - 25 条图片消息逐张验证（Playwright Chromium 与 Electron 30.5.1 CDP 各跑一遍）：分布在 8 个会话，26 个唯一 URL 全部 HTTP 200；25 张 JPEG + 1 张 PNG，`naturalWidth/naturalHeight` 均大于 0；每张点击后 lightbox 均打开并加载 `original_url`。两轮均为 0 个内联失败、0 个 lightbox 失败。其中李翔龙 1 张为 1280×1706 完整原图，其余 24 张本地只有缩略图，lightbox 与内联图一致。截图：`weimsg-25-images-check.png`、`electron-25-images-check.png`
  - 动画类验证：25 条图片在 Chromium 与 Electron 中全部 `ImageDecoder.frameCount=1`（无动画）；另用 4 帧合成 GIF 经同一 `/media/image/` 路由验证，返回 200 `image/gif`、`frameCount=4`，单元测试确认 GIF 不会被 `wxgf` 转码逻辑改写
  - 6 条视频消息全部带缩略图、时长和大小；李翔龙 1 条有完整 MP4，其余 5 条只有缩略图
  - 引用消息：4 条均渲染 `.quote-block`（发送者 + 摘要）+ `.quote-body`，页面内不再出现拍平的“（引用 …）”文本
  - 引用跳转：4 条引用的 `refer.svrid` 全部匹配到原消息；点击后消息列表滚动到原消息（目标行进入可视区），原消息气泡出现 2.2s 绿色高亮动画。截图：`web-data/screenshots/weimsg-quote-jump.png`
  - 本地文件：索引到 5 个微信本地文件（3 个 Office、2 个 rar）；6 条文件消息中 5 条成功匹配本地副本（含 2 条重复 rar 消息），APK 因微信未下载显示“本地未找到”
  - `/api/local-file/<token>`：200 返回 xlsx，sha256 与微信本地文件一致；`Range: bytes=0-99` 返回 206 + `Content-Range: bytes 0-99/13600`；未知 token 返回 404
  - 文件操作：`reveal` 请求经 outbox → 宿主机 `FileActionWorker` 执行 `open -R`，返回 `done`（真实打开 Finder）；`open` 用测试文本文件真实启动默认应用并返回 `done`
  - 文件卡片（真实页面）：目标群 3 张 Office 卡片，图标/文件名/大小/两个操作按钮正确；点击“打开位置”后页面提示“已在 Finder 中显示文件”。截图：`web-data/screenshots/weimsg-local-files.png`
  - 文件预览（独立测试快照 + 真实浏览器）：图片文件点击后 lightbox 打开且 `naturalWidth=1`；文本文件点击后弹层加载出真实文本内容
  - 表情：目标群 15 个表情 token 全部渲染为 `.wx-emoji`，其中 `[破涕为笑]` → 😂
  - 视频弹层：未缓存时显示缩略图 + “原视频尚未缓存到本地”；用 Playwright 拦截快照注入本地测试 MP4 后，`<video>` 可见、`readyState=4`、`duration=2`、自动播放成功
  - 发送一条新消息后，页面在约 11 秒内自动出现（DB 同步 3s + 快照 3s + UI 轮询 3s 的叠加）
  - 从 Web 输入框发送消息：`/api/send` → outbox → 宿主机 `/send` → 微信 UI 实际发出，`verified=true`；页面随后显示新气泡
  - 非测试联系人：向 `笑笑-金词宝推荐官` 发送成功，`verified=true`，宿主机通过侧栏滚动定位到目标会话
  - 新收到的图片：内联缩略图 157×210；完整 `.dat` 解密为 `wxgf`，由 `ffmpeg` 转出 1280×1706 JPEG。`/media/image/2026-10/508c..._full.jpg` 返回 200 `image/jpeg`、325,619 字节；点击后 lightbox 的 `naturalWidth=1280`、`naturalHeight=1706`
  - 新收到的视频（2,550,717 字节）：`/api/local-file/<token>` 支持 `Range`，返回 206；完整下载 sha256 与微信本地 MP4 一致；页面 `<video>` `readyState=4`、`duration=33.595`、`videoWidth=720`、`videoHeight=1280`，实际播放成功。截图：`weimsg-local-image-lightbox.png`、`weimsg-local-video-playback.png`
  - Electron 30.5.1 真实窗口（CDP 验证）：UA 为 `weimsg-pilot-desktop/1.0.0 ... Electron/30.5.1`；文件消息 `local_path` 为微信目录绝对路径；`Range: bytes=0-0` 返回 206 与 `Content-Range: bytes 0-0/13600`；原图 lightbox 1280×1706；本地视频 `readyState=4` 并实际播放。截图：`electron-original-image.png`、`electron-video-playback.png`
  - 文件消息：6 条中有 5 条匹配到本地文件；`/api/state` 对应 `media.local_path` 均为微信目录下的绝对路径，APK 未下载时为 `null`
  - 验证截图：`web-data/screenshots/weimsg-send.png`、`weimsg-send-other.png`、`weimsg-profile-contact.png`、`weimsg-profile-group.png`、`weimsg-local-image-lightbox.png`、`weimsg-local-video-playback.png`、`weimsg-25-images-check.png`、`electron-original-image.png`、`electron-video-playback.png`、`electron-25-images-check.png`
- Electron：`WeMsg Pilot-1.0.0-arm64.dmg` / `.zip` / `.app` 构建成功，输出在
  `~/Library/Application Support/WeMsgPilot/dist`
  - 本地构建跳过签名（`identity: null`），线上分发前请配置自己的 Apple 证书/公证
  - `config.json` 已打进 asar，`webUiUrl` 为构建时的 `WEB_UI_URL`
- 验证截图（私有，不提交）：`web-data/screenshots/`

## 数据与隐私

- `web-data/` 是明文聊天、媒体、头像和本地文件 token 索引的派生副本，权限 0700/0600，已加入 `.gitignore`。`local-files.json` 只记录相对路径；绝对路径仅写入本机 DuckDB `local_files` 表和快照文件消息的 `media.local_path`，供本机 Electron 定位。
- Docker 容器只读挂载快照和微信 `xwechat_files`；不包含微信密钥、原始数据库或 macOS 权限。HTTP 文件读取只能按索引 token 解析，且再次校验路径 containment，不能遍历任意宿主路径。
- 快照会向页面暴露已索引文件的宿主机绝对路径（仅文件消息、且仅在本机私有部署前提下的 MVP 行为）；对公网部署前应改为按需接口并加鉴权。
- “打开/打开位置”由宿主机 `FileActionWorker` 执行，容器本身不运行 macOS `open`。
- 线上部署时请使用自己的 HTTPS 域名和访问控制；本 MVP 不自带鉴权。
- 语音转写：当前账号 0 条语音；`transcripts` 表为空，UI 显示“无音频/无转写”。
- 图片/视频缩略图关联依赖宿主机已解密的 `message_resource.db`。启动后**新收到**的图片/视频如果在解密快照里还没有 resource 记录，会先显示占位；重新运行宿主机解密/导入后补齐。
- 本机 25 条图片消息中只有李翔龙 1 条存在完整 `.dat` 原图（1280×1706）；其余 24 条微信本地仅缓存 `_t.dat` 缩略图（实测 75×124 到 300×400，各图尺寸不一），页面无法凭空放大出原图。当前没有动画图片源；动画 GIF/WebP/APNG 会原样展示，动画 WXGF 未在真实数据中出现，也未做多帧转码。
- 文件消息匹配规则是“文件名完全相同 + 字节数相同”，找不到时回退“字节数 + 扩展名唯一”；同名文件优先匹配消息所在月份目录。微信改过文件名或本地文件被清理后会显示“本地未找到”。
- Office/压缩包不在页面内渲染，点击“打开”由宿主机调用默认应用；页面内预览只覆盖图片、视频、音频、PDF 和纯文本。
- 视频播放依赖微信已把完整文件下载到 `msg/video/**`。`sync_agent` 扫描该目录并按消息里的字节数匹配，直接返回本地文件。本机 6 条视频中李翔龙 1 条已缓存完整 MP4（2,550,717 字节，已验证播放）；其余 5 条只有 `_thumb.jpg`，弹层显示“原视频尚未缓存到本地”。在微信里播放一次后会出现在索引中。
- 本机文件消息里的 APK（319 MB）微信尚未下载，因此卡片显示“本地未找到”，不提供打开操作。
- 本地 `videomsg` XML 里的 `cdnvideourl` 是微信协议的文件 ID，不是 iLink CDN 的 `encrypt_query_param`；本项目没有走 CDN 直连下载，也没有修改微信客户端数据。
- 会话资料来自已解密的 `contact.db` / `head_image.db`；启动后新增联系人、改备注或换头像，需要重新解密/导入后才会更新。
- 本机 `contact_label` 表为空，快照中 `tags` 为 `[]`，UI 显示“暂无标签”；联系人↔标签映射尚未实现，后续需要补充数据源。
- 群公告只显示本地已解密的公告文本；收藏、图片附件等未接入资料面板。
- Web UI 默认允许任意会话发送；宿主机先定位会话、核对标题，再输入/发送。
- 任意会话依赖微信侧栏能滚动定位到目标；找不到时返回 `chat_not_found`，不会盲发。
- 同名会话存在歧义；发送前请核对页面会话与微信标题。
- 发送依赖宿主机 `make sync` 的 `SendWorker`；如果只运行快照或 worker 停止，请求会停留在队列。
- 发送会激活 Mac 微信前台，并可能短暂占用剪贴板；单条消息限制 500 字、单行。
- 同一请求由宿主机按 `request_id` 幂等；失败不会自动重发。
