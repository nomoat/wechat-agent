(() => {
  "use strict";

  const POLL_MS = 3000;
  const els = {
    app: document.getElementById("app"),
    statusDot: document.getElementById("status-dot"),
    search: document.getElementById("search"),
    conversationList: document.getElementById("conversation-list"),
    updatedAt: document.getElementById("updated-at"),
    chatTitle: document.getElementById("chat-title"),
    chatSubtitle: document.getElementById("chat-subtitle"),
    messageList: document.getElementById("message-list"),
    newMessages: document.getElementById("new-messages"),
    backButton: document.getElementById("back-button"),
    chatAvatar: document.getElementById("chat-avatar"),
    profileToggle: document.getElementById("profile-toggle"),
    profilePanel: document.getElementById("profile-panel"),
    profileClose: document.getElementById("profile-close"),
    profileAvatar: document.getElementById("profile-avatar"),
    profileName: document.getElementById("profile-name"),
    profileKind: document.getElementById("profile-kind"),
    profileRemark: document.getElementById("profile-remark"),
    profileNickname: document.getElementById("profile-nickname"),
    profileAlias: document.getElementById("profile-alias"),
    profileAliasSection: document.getElementById("profile-alias-section"),
    profileTags: document.getElementById("profile-tags"),
    profileDescription: document.getElementById("profile-description"),
    profileAnnouncement: document.getElementById("profile-announcement"),
    profileAnnouncementSection: document.getElementById(
      "profile-announcement-section"
    ),
    profileAnnouncementMeta: document.getElementById("profile-announcement-meta"),
    profileMeta: document.getElementById("profile-meta"),
    composerInput: document.getElementById("composer-input"),
    sendButton: document.getElementById("send-button"),
    composerHint: document.getElementById("composer-hint"),
    lightbox: document.getElementById("lightbox"),
    lightboxImg: document.getElementById("lightbox-img"),
    lightboxClose: document.getElementById("lightbox-close"),
    videoModal: document.getElementById("video-modal"),
    videoPlayer: document.getElementById("video-player"),
    videoMissing: document.getElementById("video-missing"),
    videoClose: document.getElementById("video-close"),
    videoRetry: document.getElementById("video-retry"),
    fileModal: document.getElementById("file-modal"),
    fileTitle: document.getElementById("file-modal-title"),
    fileContent: document.getElementById("file-modal-content"),
    fileClose: document.getElementById("file-close"),
    toast: document.getElementById("toast"),
  };

  const state = {
    snapshot: null,
    selected: null,
    search: "",
    lastSeen: loadSeen(),
    initialized: false,
    lastSignature: "",
    stickToBottom: true,
    pendingNew: false,
    sendEnabled: false,
    sending: false,
    profileOpen: window.innerWidth > 1180,
    toastTimer: null,
    videoChat: null,
    videoLocalId: null,
    highlight: null,
    highlightTimer: null,
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function loadSeen() {
    try {
      const raw = JSON.parse(localStorage.getItem("weimsg.seen") || "{}");
      const clean = {};
      for (const [key, value] of Object.entries(raw)) {
        const number = Number(value);
        if (Number.isFinite(number)) clean[key] = number;
      }
      return clean;
    } catch (_) {
      return {};
    }
  }

  function saveSeen() {
    try {
      localStorage.setItem("weimsg.seen", JSON.stringify(state.lastSeen));
    } catch (_) {
      /* private mode / storage disabled */
    }
  }

  function hashHue(value) {
    let hash = 0;
    for (const char of String(value || "?")) {
      hash = (hash * 31 + char.codePointAt(0)) % 360;
    }
    return hash;
  }

  function initial(value) {
    const text = String(value || "?").trim();
    if (!text) return "?";
    return /^[A-Za-z]/.test(text)
      ? text.slice(0, 2).toUpperCase()
      : text.slice(0, 1);
  }

  function avatar(name, small = false, url = null) {
    const node = document.createElement("div");
    node.className = "avatar" + (small ? " small" : "");
    node.style.setProperty("--hue", String(hashHue(name)));
    if (url) {
      const image = document.createElement("img");
      image.className = "avatar-img";
      image.src = url;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => {
        image.remove();
        node.textContent = initial(name);
      });
      node.append(image);
    } else {
      node.textContent = initial(name);
    }
    return node;
  }

  function fillAvatar(container, name, url) {
    container.replaceChildren();
    container.style.setProperty("--hue", String(hashHue(name)));
    if (url) {
      const image = document.createElement("img");
      image.className = "avatar-img";
      image.src = url;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => {
        image.remove();
        container.textContent = initial(name);
      });
      container.append(image);
    } else {
      container.textContent = initial(name);
    }
  }

  function profileFor(conversation) {
    if (!conversation) return {};
    return state.snapshot?.profiles?.[conversation.username] || {};
  }

  function formatDateTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "";
    const date = new Date(value * 1000);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (number) => String(number).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
      date.getDate()
    )} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function setProfileField(element, value, fallback) {
    element.textContent = value || fallback;
  }

  function addProfileMeta(label, value) {
    if (!value) return;
    const line = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = label;
    line.append(strong, document.createTextNode(String(value)));
    els.profileMeta.append(line);
  }

  function conversationMessages(conversation) {
    return (state.snapshot?.messages?.[conversation.username] || []);
  }

  function lastMessage(conversation) {
    const messages = conversationMessages(conversation);
    return messages.length ? messages[messages.length - 1] : null;
  }

  function sortedConversations() {
    const list = [...(state.snapshot?.conversations || [])];
    list.sort((left, right) => {
      const a = lastMessage(left)?.timestamp || 0;
      const b = lastMessage(right)?.timestamp || 0;
      return b - a;
    });
    return list;
  }

  function isGroup(conversation) {
    return String(conversation?.username || "").includes("@chatroom");
  }

  function messageTime(message) {
    const value = Number(message?.timestamp);
    return Number.isFinite(value) ? value : 0;
  }

  function dateOf(message) {
    return String(message?.time || "").slice(0, 10);
  }

  function formatClock(time) {
    const date = new Date(String(time || "").replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return "";
    return `${String(date.getHours()).padStart(2, "0")}:${String(
      date.getMinutes()
    ).padStart(2, "0")}`;
  }

  function formatSidebarTime(time) {
    const date = new Date(String(time || "").replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return "";
    const now = new Date();
    const sameDay =
      date.getFullYear() === now.getFullYear() &&
      date.getMonth() === now.getMonth() &&
      date.getDate() === now.getDate();
    if (sameDay) return formatClock(time);
    return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(
      date.getDate()
    ).padStart(2, "0")}`;
  }

  function formatDay(time) {
    const date = new Date(String(time || "").replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return "";
    const now = new Date();
    const sameYear = date.getFullYear() === now.getFullYear();
    return sameYear
      ? `${date.getMonth() + 1}月${date.getDate()}日`
      : `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
  }

  function formatDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "";
    const minutes = Math.floor(value / 60);
    const rest = Math.floor(value % 60);
    return `${minutes}:${String(rest).padStart(2, "0")}`;
  }

  function formatSize(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) return "";
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }

  function previewText(message) {
    return window.WeMsgMessageUtils.previewText(message);
  }

  function renderRichText(container, text) {
    for (const part of window.WeMsgMessageUtils.richTextParts(text)) {
      if (part.type === "emoji") {
        const emoji = document.createElement("span");
        emoji.className = "wx-emoji";
        emoji.textContent = part.value;
        emoji.title = `[${part.name}]`;
        container.append(emoji);
      } else {
        container.append(document.createTextNode(part.value));
      }
    }
  }

  function isNearBottom() {
    const list = els.messageList;
    return list.scrollHeight - list.scrollTop - list.clientHeight < 90;
  }

  function scrollToBottom() {
    els.messageList.scrollTop = els.messageList.scrollHeight;
  }

  function toast(text) {
    els.toast.textContent = text;
    els.toast.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => els.toast.classList.remove("show"), 2600);
  }

  function openLightbox(url) {
    if (!url) return;
    els.lightboxImg.src = url;
    els.lightbox.classList.remove("hidden");
  }

  function closeLightbox() {
    els.lightbox.classList.add("hidden");
    els.lightboxImg.removeAttribute("src");
  }

  function selectChat(username, openMobile = true) {
    const conversation = (state.snapshot?.conversations || []).find(
      (item) => item.username === username
    );
    if (!conversation) return;
    state.selected = username;
    state.stickToBottom = true;
    state.pendingNew = false;
    state.lastSignature = "";
    const last = lastMessage(conversation);
    state.lastSeen[username] = last ? messageTime(last) : 0;
    saveSeen();
    if (openMobile && window.innerWidth <= 760) {
      els.app.classList.add("chat-open");
    }
    render();
    requestAnimationFrame(scrollToBottom);
    setTimeout(() => {
      if (state.stickToBottom) scrollToBottom();
    }, 300);
  }

  function initializeSeen() {
    for (const conversation of state.snapshot?.conversations || []) {
      if (!(conversation.username in state.lastSeen)) {
        const last = lastMessage(conversation);
        state.lastSeen[conversation.username] = last ? messageTime(last) : 0;
      }
    }
    saveSeen();
  }

  function unreadCount(conversation) {
    if (conversation.username === state.selected) return 0;
    const seen = Number(state.lastSeen[conversation.username] || 0);
    return conversationMessages(conversation).filter(
      (message) => messageTime(message) > seen
    ).length;
  }

  function renderConversations() {
    const query = state.search.trim().toLowerCase();
    const fragment = document.createDocumentFragment();
    const conversations = sortedConversations().filter((conversation) => {
      if (!query) return true;
      const last = lastMessage(conversation);
      return (
        String(conversation.display_name || "").toLowerCase().includes(query) ||
        previewText(last).toLowerCase().includes(query)
      );
    });

    for (const conversation of conversations) {
      const last = lastMessage(conversation);
      const row = document.createElement("div");
      row.className =
        "conversation" +
        (conversation.username === state.selected ? " active" : "");
      row.title = conversation.display_name;
      row.addEventListener("click", () => selectChat(conversation.username));

      row.append(
        avatar(
          conversation.display_name,
          false,
          profileFor(conversation).avatar_url
        )
      );

      const main = document.createElement("div");
      main.className = "conversation-main";

      const top = document.createElement("div");
      top.className = "conversation-top";

      const name = document.createElement("div");
      name.className = "conversation-name";
      name.textContent = conversation.display_name || conversation.username;

      const time = document.createElement("div");
      time.className = "conversation-time";
      time.textContent = formatSidebarTime(last?.time || conversation.last_time);

      top.append(name, time);

      const preview = document.createElement("div");
      preview.className = "conversation-preview";
      preview.textContent = previewText(last);

      main.append(top, preview);
      row.append(main);

      const unread = unreadCount(conversation);
      if (unread > 0) {
        const badge = document.createElement("span");
        badge.className = "unread-badge";
        badge.textContent = unread > 99 ? "99+" : String(unread);
        row.append(badge);
      }

      fragment.append(row);
    }

    if (!conversations.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML =
        "<p>没有匹配的会话</p><small>等待宿主机同步或换个关键词</small>";
      fragment.append(empty);
    }

    els.conversationList.replaceChildren(fragment);
  }

  function openVideo(message) {
    const media = message?.media || {};
    state.videoChat = state.selected;
    state.videoLocalId = message?.local_id ?? null;
    if (media.url) {
      els.videoMissing.classList.add("hidden");
      els.videoPlayer.classList.remove("hidden");
      els.videoPlayer.poster = media.thumbnail || "";
      els.videoPlayer.src = media.url;
      els.videoModal.classList.remove("hidden");
      const playing = els.videoPlayer.play();
      if (playing?.catch) playing.catch(() => {});
      return;
    }
    els.videoPlayer.pause();
    els.videoPlayer.removeAttribute("src");
    els.videoPlayer.load();
    els.videoPlayer.classList.add("hidden");
    els.videoMissing.classList.remove("hidden");
    els.videoMissing.style.backgroundImage = media.thumbnail
      ? `url("${media.thumbnail}")`
      : "";
    els.videoModal.classList.remove("hidden");
  }

  function closeVideo() {
    els.videoPlayer.pause();
    els.videoPlayer.removeAttribute("src");
    els.videoPlayer.load();
    els.videoModal.classList.add("hidden");
    state.videoChat = null;
    state.videoLocalId = null;
  }

  const FILE_ICONS = {
    image: "🖼️",
    video: "🎬",
    audio: "🎵",
    pdf: "📕",
    text: "📃",
    office: "📊",
    archive: "🗜️",
    other: "📦",
  };

  function closeFileModal() {
    els.fileContent
      .querySelectorAll("audio, video")
      .forEach((item) => {
        item.pause();
        item.removeAttribute("src");
      });
    els.fileContent.replaceChildren();
    els.fileTitle.textContent = "";
    els.fileModal.classList.add("hidden");
  }

  async function openFileModal(media) {
    els.fileTitle.textContent = media.name || "文件";
    els.fileContent.replaceChildren();
    els.fileModal.classList.remove("hidden");
    if (media.category === "pdf") {
      const frame = document.createElement("iframe");
      frame.className = "file-frame";
      frame.src = media.url;
      frame.title = media.name || "PDF";
      els.fileContent.append(frame);
      return;
    }
    if (media.category === "audio") {
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.autoplay = true;
      audio.src = media.url;
      els.fileContent.append(audio);
      return;
    }
    const text = document.createElement("pre");
    text.className = "file-preview-text";
    text.textContent = "加载中…";
    els.fileContent.append(text);
    try {
      const response = await fetch(media.url);
      if (!response.ok) throw new Error("文件读取失败");
      const content = await response.text();
      text.textContent =
        content.length > 200000
          ? `${content.slice(0, 200000)}\n…（内容过长，已截断）`
          : content;
    } catch (error) {
      text.textContent = error?.message || "文件读取失败";
    }
  }

  async function pollFileAction(requestId) {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      try {
        const response = await fetch(`/api/file-action/${requestId}`);
        if (!response.ok) break;
        const result = await response.json();
        if (result.status === "done") {
          toast(
            result.action === "reveal"
              ? "已在 Finder 中显示文件"
              : "已用默认应用打开"
          );
          return;
        }
        if (result.status === "failed") {
          toast(`操作失败：${result.error || "未知错误"}`);
          return;
        }
      } catch (error) {
        break;
      }
    }
    toast("宿主机未响应，请确认 make sync 正在运行");
  }

  async function runFileAction(media, action) {
    if (!media?.token) {
      toast("微信本地保存目录中没有找到该文件");
      return;
    }
    try {
      const response = await fetch(
        `/api/local-file/${media.token}/action`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action }),
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail?.message || "请求失败");
      }
      const payload = await response.json();
      toast(action === "reveal" ? "正在打开文件位置…" : "正在打开文件…");
      pollFileAction(payload.request_id);
    } catch (error) {
      toast(error?.message || "操作失败");
    }
  }

  function openFilePreview(message) {
    const media = message?.media || {};
    if (!media.url) {
      toast("微信本地保存目录中没有找到该文件，请先在微信中下载或打开一次");
      return;
    }
    if (media.category === "image") {
      openLightbox(media.url);
      return;
    }
    if (media.category === "video") {
      openVideo(message);
      return;
    }
    if (["audio", "pdf", "text"].includes(media.category)) {
      openFileModal(media);
      return;
    }
    runFileAction(media, "open");
  }

  function jumpToMessage(localId) {
    const row = els.messageList.querySelector(
      `.message-row[data-local-id="${String(localId)}"]`
    );
    if (!row) {
      toast("引用的消息不在当前同步范围内");
      return;
    }
    state.stickToBottom = false;
    state.highlight = { localId: String(localId), until: Date.now() + 2200 };
    els.messageList
      .querySelectorAll(".message-row.quote-target")
      .forEach((item) => item.classList.remove("quote-target"));
    row.classList.add("quote-target");
    row.scrollIntoView({ behavior: "instant", block: "center" });
    clearTimeout(state.highlightTimer);
    state.highlightTimer = setTimeout(() => {
      state.highlight = null;
      els.messageList
        .querySelectorAll(".message-row.quote-target")
        .forEach((item) => item.classList.remove("quote-target"));
    }, 2200);
  }

  function jumpToQuotedMessage(quote) {
    const conversation = (state.snapshot?.conversations || []).find(
      (item) => item.username === state.selected
    );
    const message = conversation
      ? window.WeMsgMessageUtils.findQuotedMessage(
          conversationMessages(conversation),
          quote
        )
      : null;
    if (!message) {
      toast("引用的消息不在当前同步范围内");
      return;
    }
    jumpToMessage(message.local_id);
  }

  function renderQuote(bubble, quote) {
    const block = document.createElement("div");
    block.className = "quote-block quote-jump";
    block.title = "点击跳转到原消息";
    block.tabIndex = 0;
    block.setAttribute("role", "button");
    const jump = () => jumpToQuotedMessage(quote);
    block.addEventListener("click", jump);
    block.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        jump();
      }
    });
    const head = document.createElement("div");
    head.className = "quote-head";
    const sender = document.createElement("span");
    sender.className = "quote-sender";
    sender.textContent = quote.refer.sender;
    const colon = document.createElement("span");
    colon.className = "quote-colon";
    colon.textContent = "：";
    const summary = document.createElement("span");
    summary.className = "quote-summary";
    renderRichText(summary, quote.refer.summary);
    head.append(sender, colon, summary);
    block.append(head);
    bubble.append(block);

    const body = document.createElement("div");
    body.className = "quote-body";
    if (quote.text) renderRichText(body, quote.text);
    if (quote.text) bubble.append(body);
  }

  function renderBubble(bubble, message) {
    const media = message.media || null;
    const type = Number(message.type);

    if (media?.kind === "image" || type === 3) {
      if (media?.url) {
        const image = document.createElement("img");
        image.className = "media-image";
        image.src = media.url;
        image.alt = "图片";
        image.loading = "lazy";
        image.addEventListener("click", () =>
          openLightbox(window.WeMsgMessageUtils.imagePreviewUrl(media))
        );
        image.addEventListener("load", () => {
          if (state.stickToBottom) scrollToBottom();
        });
        bubble.append(image);
      } else {
        const placeholder = document.createElement("div");
        placeholder.className = "media-placeholder";
        placeholder.textContent = "图片（未解密或文件缺失）";
        bubble.append(placeholder);
      }
      return;
    }

    if (media?.kind === "video" || type === 43) {
      const card = document.createElement("div");
      card.className = "video-card";
      if (media?.thumbnail) {
        const thumb = document.createElement("img");
        thumb.className = "video-thumb";
        thumb.src = media.thumbnail;
        thumb.alt = "";
        card.append(thumb);
      }
      const shade = document.createElement("div");
      shade.className = "video-shade";
      const play = document.createElement("div");
      play.className = "video-play";
      play.textContent = "▶";
      const meta = document.createElement("div");
      meta.className = "video-meta";
      const duration = document.createElement("span");
      duration.className = "duration";
      duration.textContent = formatDuration(media?.duration) || "视频";
      const size = document.createElement("span");
      size.className = "video-label";
      size.textContent = formatSize(media?.size);
      meta.append(duration, size);
      card.append(shade, play, meta);
      card.addEventListener("click", () => openVideo(message));
      bubble.append(card);
      return;
    }

    if (media?.kind === "voice" || type === 34) {
      const wrapper = document.createElement("div");
      wrapper.className = "voice-bubble";
      const line = document.createElement("div");
      line.className = "voice-line";
      const wave = document.createElement("span");
      wave.className = "wave";
      for (let index = 0; index < 5; index += 1) {
        wave.append(document.createElement("span"));
      }
      const duration = document.createElement("span");
      duration.className = "voice-duration";
      duration.textContent = media?.duration
        ? `${media.duration}″`
        : "语音";
      line.append(wave, duration);
      wrapper.append(line);
      if (media?.transcript) {
        const transcript = document.createElement("div");
        transcript.className = "voice-transcript";
        transcript.textContent = media.transcript;
        wrapper.append(transcript);
      } else {
        const missing = document.createElement("div");
        missing.className = "voice-missing";
        missing.textContent = "语音消息（无音频/无转写）";
        wrapper.append(missing);
      }
      bubble.append(wrapper);
      return;
    }

    if (media?.kind === "file") {
      const category =
        media.category ||
        window.WeMsgMessageUtils.fileCategory(media.name);
      const available = Boolean(media.url) && media.available !== false;
      const card = document.createElement("div");
      card.className = `file-card file-${category}`;
      card.setAttribute("role", "button");
      card.tabIndex = 0;
      card.title = available
        ? "点击预览或用默认应用打开"
        : "微信本地保存目录中没有找到该文件";
      const icon = document.createElement("div");
      icon.className = "file-icon";
      icon.textContent = FILE_ICONS[category] || FILE_ICONS.other;
      const info = document.createElement("div");
      info.className = "file-info";
      const name = document.createElement("div");
      name.className = "file-name";
      name.textContent = media.name || "文件";
      const size = document.createElement("div");
      size.className = `file-size${available ? "" : " file-unavailable"}`;
      size.textContent = available
        ? formatSize(media.size)
        : `${formatSize(media.size) || "文件"} · 本地未找到`;
      info.append(name, size);
      const actions = document.createElement("div");
      actions.className = "file-actions";
      [
        ["打开", "open"],
        ["打开位置", "reveal"],
      ].forEach(([label, action]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "file-action";
        button.textContent = label;
        button.disabled = !available;
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          runFileAction(media, action);
        });
        actions.append(button);
      });
      card.append(icon, info, actions);
      card.addEventListener("click", () => openFilePreview(message));
      card.addEventListener("keydown", (event) => {
        if (event.target !== card) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openFilePreview(message);
        }
      });
      bubble.append(card);
      return;
    }

    const quote = window.WeMsgMessageUtils.parseQuote(message);
    if (quote) {
      renderQuote(bubble, quote);
      return;
    }

    renderRichText(
      bubble,
      message.content || `[${message.type_name || "消息"}]`
    );
  }

  function renderMessages() {
    const conversation = (state.snapshot?.conversations || []).find(
      (item) => item.username === state.selected
    );
    if (!conversation) {
      els.chatTitle.textContent = "选择一个会话";
      els.chatSubtitle.textContent = "左侧是群聊和联系人，右侧显示实际消息";
      fillAvatar(els.chatAvatar, "?", null);
      els.messageList.innerHTML =
        '<div class="empty-state"><div class="empty-icon">💬</div><p>从左侧选择一个群聊或联系人</p><small>消息来自本机 DuckDB 快照，页面每 3 秒刷新</small></div>';
      return;
    }

    const messages = conversationMessages(conversation);
    const group = isGroup(conversation);
    const profile = profileFor(conversation);
    fillAvatar(
      els.chatAvatar,
      conversation.display_name || conversation.username,
      profile.avatar_url
    );
    els.chatTitle.textContent =
      profile.display_name ||
      conversation.display_name ||
      conversation.username;
    els.chatSubtitle.textContent = `${messages.length} 条消息 · ${
      group ? "群聊" : "联系人"
    } · 每 3 秒刷新`;

    const signature = `${conversation.username}:${messages.length}:${
      messages[messages.length - 1]?.local_id ?? ""
    }`;
    const hasNew = signature !== state.lastSignature;
    const stick = state.stickToBottom;
    const fragment = document.createDocumentFragment();
    let lastTimestamp = 0;
    let lastDay = "";

    for (const message of messages) {
      const type = Number(message.type);
      if (type === 10000 || String(message.type_name || "").includes("系统")) {
        const system = document.createElement("div");
        system.className = "system-message";
        system.textContent = message.content || "系统消息";
        fragment.append(system);
        continue;
      }

      const timestamp = messageTime(message);
      const day = dateOf(message);
      const gap = lastTimestamp && timestamp ? timestamp - lastTimestamp : 0;
      if (!lastDay || day !== lastDay || gap > 300) {
        const separator = document.createElement("div");
        separator.className = "message-separator";
        separator.textContent =
          day !== lastDay
            ? `${formatDay(message.time)} ${formatClock(message.time)}`
            : formatClock(message.time);
        fragment.append(separator);
      }

      const row = document.createElement("div");
      row.className = "message-row" + (message.is_self ? " self" : "");
      row.dataset.localId = String(message.local_id);
      if (
        state.highlight &&
        state.highlight.localId === row.dataset.localId &&
        Date.now() < state.highlight.until
      ) {
        row.classList.add("quote-target");
      }
      const incomingAvatar = !group && !message.is_self ? profile.avatar_url : null;
      row.append(
        avatar(
          message.is_self ? "我" : message.sender || "对方",
          true,
          incomingAvatar
        )
      );

      const body = document.createElement("div");
      body.className = "message-body";

      if (!message.is_self && group) {
        const sender = document.createElement("div");
        sender.className = "sender-name";
        sender.textContent = message.sender || "群成员";
        body.append(sender);
      }

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      renderBubble(bubble, message);
      body.append(bubble);
      row.append(body);
      fragment.append(row);

      lastTimestamp = timestamp;
      lastDay = day;
    }

    els.messageList.replaceChildren(fragment);
    state.lastSignature = signature;
    if (stick) {
      state.pendingNew = false;
      requestAnimationFrame(scrollToBottom);
      setTimeout(() => {
        if (state.stickToBottom) scrollToBottom();
      }, 300);
    } else if (hasNew) {
      state.pendingNew = true;
    }
    els.newMessages.classList.toggle("hidden", !state.pendingNew);
  }

  function renderComposer() {
    const conversation = (state.snapshot?.conversations || []).find(
      (item) => item.username === state.selected
    );
    const allowed = Boolean(conversation && state.sendEnabled);
    els.composerInput.disabled = !allowed || state.sending;
    els.sendButton.disabled =
      !allowed || state.sending || !els.composerInput.value.trim();
    els.sendButton.classList.toggle("sending", state.sending);
    els.composerInput.placeholder = allowed ? "输入消息…" : "发送不可用";
    els.composerHint.textContent = allowed
      ? state.sending
        ? "正在通过微信 UI 定位会话并发送…"
        : "实际发送由 Mac 微信 UI 自动化完成；发送前会定位并核对会话"
      : "发送服务未启用";
    els.sendButton.textContent = state.sending ? "发送中…" : "发送";
  }

  async function loadConfig() {
    try {
      const response = await fetch("/api/config", { cache: "no-store" });
      if (response.ok) {
        const data = await response.json();
        state.sendEnabled = data.send_enabled !== false;
      }
    } catch (_) {
      state.sendEnabled = false;
    }
    renderComposer();
  }

  async function pollSend(requestId) {
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      await sleep(1000);
      try {
        const response = await fetch(`/api/send/${requestId}`, {
          cache: "no-store",
        });
        if (!response.ok) continue;
        const data = await response.json();
        if (data.status !== "pending") return data;
      } catch (_) {
        /* retry */
      }
    }
    return { status: "timeout" };
  }

  async function sendMessage() {
    if (state.sending) return;
    const conversation = (state.snapshot?.conversations || []).find(
      (item) => item.username === state.selected
    );
    if (!conversation || !state.sendEnabled) return;
    const text = els.composerInput.value.trim();
    if (!text) return;

    state.sending = true;
    renderComposer();
    toast("已加入发送队列，正在调用微信 UI…");
    try {
      const response = await fetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat: conversation.username,
          display_name: conversation.display_name,
          text,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status !== 202) {
        const detail = payload.detail;
        const message =
          detail?.message ||
          (Array.isArray(detail) ? detail[0]?.msg : null) ||
          `HTTP ${response.status}`;
        throw new Error(message);
      }
      const result = await pollSend(payload.request_id);
      if (result.status === "sent") {
        els.composerInput.value = "";
        toast("已发送并验证：微信 UI 已出现新气泡");
      } else if (result.status === "sent_unverified") {
        els.composerInput.value = "";
        toast("已发送，但未看到气泡，请人工确认");
      } else if (result.status === "timeout") {
        toast("发送结果未知，请查看微信窗口，勿立即重试");
      } else {
        const detail = result.detail;
        const message =
          result.error ||
          detail?.message ||
          (Array.isArray(detail) ? detail[0]?.msg : null) ||
          result.status;
        toast(`发送失败：${message}`);
      }
    } catch (error) {
      toast(`发送失败：${error.message}`);
    } finally {
      state.sending = false;
      renderComposer();
      load();
    }
  }

  function renderProfile() {
    const conversation = (state.snapshot?.conversations || []).find(
      (item) => item.username === state.selected
    );
    const profile = profileFor(conversation);
    const hasConversation = Boolean(conversation);
    els.profilePanel.classList.toggle(
      "closed",
      !hasConversation || !state.profileOpen
    );
    if (!hasConversation) return;

    const kind =
      profile.kind || (isGroup(conversation) ? "group" : "contact");
    const name =
      profile.display_name ||
      conversation.display_name ||
      conversation.username;
    els.profileName.textContent = name;
    els.profileKind.textContent =
      kind === "group"
        ? `群聊${profile.member_count ? ` · ${profile.member_count} 人` : ""}`
        : "联系人";
    fillAvatar(els.profileAvatar, name, profile.avatar_url);

    setProfileField(els.profileRemark, profile.remark, "暂无备注");
    setProfileField(els.profileNickname, profile.nick_name, "暂无昵称");
    const alias = profile.alias || "";
    els.profileAliasSection.classList.toggle(
      "hidden",
      kind === "group" && !alias
    );
    setProfileField(els.profileAlias, alias, "暂无微信号");

    els.profileTags.replaceChildren();
    const tags = Array.isArray(profile.tags)
      ? profile.tags.filter(Boolean)
      : [];
    if (!tags.length) {
      const tag = document.createElement("span");
      tag.className = "tag empty";
      tag.textContent = "暂无标签";
      els.profileTags.append(tag);
    } else {
      for (const value of tags) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = String(value);
        els.profileTags.append(tag);
      }
    }
    setProfileField(
      els.profileDescription,
      profile.description,
      "暂无备忘/描述"
    );

    const isGroupChat = kind === "group";
    els.profileAnnouncementSection.classList.toggle("hidden", !isGroupChat);
    if (isGroupChat) {
      setProfileField(
        els.profileAnnouncement,
        profile.announcement,
        "暂无群公告"
      );
      const meta = [];
      const editor =
        profile.announcement_editor_display ||
        profile.announcement_editor;
      if (editor) meta.push(`发布者：${editor}`);
      const published = formatDateTime(profile.announcement_time);
      if (published) meta.push(`发布：${published}`);
      els.profileAnnouncementMeta.textContent = meta.join(" · ");
    }

    els.profileMeta.replaceChildren();
    if (isGroupChat) {
      addProfileMeta(
        "群成员",
        profile.member_count != null ? `${profile.member_count} 人` : "未知"
      );
      addProfileMeta("群主", profile.owner_display || profile.owner || "未知");
      addProfileMeta("群 ID", conversation.username);
    } else {
      addProfileMeta("微信号", alias || "未设置");
      addProfileMeta("用户 ID", conversation.username);
    }
  }

  function render() {
    if (!state.snapshot) {
      els.statusDot.classList.add("error");
      els.updatedAt.textContent = "等待宿主机同步…";
      renderConversations();
      renderMessages();
      renderComposer();
      renderProfile();
      return;
    }

    const conversations = sortedConversations();
    if (state.selected && !conversations.some((item) => item.username === state.selected)) {
      state.selected = null;
    }
    if (!state.selected && conversations.length && window.innerWidth > 760) {
      state.selected = conversations[0].username;
      const last = lastMessage(conversations[0]);
      state.lastSeen[state.selected] = last ? messageTime(last) : 0;
      saveSeen();
    }

    els.statusDot.classList.toggle("error", Boolean(state.error));
    els.statusDot.classList.toggle("online", !state.error);
    els.updatedAt.textContent = state.error
      ? "同步异常，显示最近快照"
      : `更新于 ${formatClock(
          new Date(state.snapshot.updated_at || Date.now())
            .toISOString()
            .replace("T", " ")
            .replace("Z", "")
        )} · ${state.snapshot.counts?.conversations ?? 0} 会话 / ${
          state.snapshot.counts?.messages ?? 0
        } 条`;

    renderConversations();
    renderMessages();
    renderComposer();
    renderProfile();
  }

  async function load() {
    try {
      const response = await fetch("/api/state", { cache: "no-store" });
      if (response.status === 503) {
        state.error = "snapshot missing";
        if (!state.snapshot) {
          els.statusDot.classList.add("error");
          els.updatedAt.textContent = "等待宿主机同步…";
        }
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.snapshot = data;
      state.error = null;
      if (!state.initialized) {
        initializeSeen();
        state.initialized = true;
      }
      render();
    } catch (error) {
      state.error = error.message || "network error";
      els.statusDot.classList.add("error");
      els.updatedAt.textContent = "连接失败，等待重试…";
    }
  }

  function bind() {
    els.search.addEventListener("input", (event) => {
      state.search = event.target.value;
      renderConversations();
    });
    els.composerInput.addEventListener("input", renderComposer);
    els.composerInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        sendMessage();
      }
    });
    els.sendButton.addEventListener("click", sendMessage);
    els.profileToggle.addEventListener("click", () => {
      state.profileOpen = !state.profileOpen;
      renderProfile();
    });
    els.profileClose.addEventListener("click", () => {
      state.profileOpen = false;
      renderProfile();
    });
    els.backButton.addEventListener("click", () => {
      els.app.classList.remove("chat-open");
    });
    els.messageList.addEventListener("scroll", () => {
      const near = isNearBottom();
      state.stickToBottom = near;
      if (near) {
        state.pendingNew = false;
        els.newMessages.classList.add("hidden");
      }
    });
    els.newMessages.addEventListener("click", () => {
      state.stickToBottom = true;
      state.pendingNew = false;
      scrollToBottom();
      els.newMessages.classList.add("hidden");
      const conversation = (state.snapshot?.conversations || []).find(
        (item) => item.username === state.selected
      );
      if (conversation) {
        const last = lastMessage(conversation);
        state.lastSeen[conversation.username] = last ? messageTime(last) : 0;
        saveSeen();
        renderConversations();
      }
    });
    els.lightboxClose.addEventListener("click", closeLightbox);
    els.lightbox.addEventListener("click", (event) => {
      if (event.target === els.lightbox) closeLightbox();
    });
    els.videoClose.addEventListener("click", closeVideo);
    els.videoModal.addEventListener("click", (event) => {
      if (event.target === els.videoModal) closeVideo();
    });
    els.fileClose.addEventListener("click", closeFileModal);
    els.fileModal.addEventListener("click", (event) => {
      if (event.target === els.fileModal) closeFileModal();
    });
    els.videoPlayer.addEventListener("error", () => {
      if (els.videoPlayer.getAttribute("src")) {
        toast("视频加载失败，文件可能仍在缓存中");
      }
    });
    els.videoRetry.addEventListener("click", async () => {
      const chat = state.videoChat;
      const localId = state.videoLocalId;
      await load();
      const conversation = (state.snapshot?.conversations || []).find(
        (item) => item.username === chat
      );
      const message = conversation
        ? conversationMessages(conversation).find(
            (item) => item.local_id === localId
          )
        : null;
      if (message?.media?.url) {
        openVideo(message);
      } else {
        toast("仍未检测到本地视频，请在微信中播放一次");
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeLightbox();
        closeVideo();
        closeFileModal();
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) load();
    });
  }

  bind();
  loadConfig();
  load();
  setInterval(load, POLL_MS);
})();
