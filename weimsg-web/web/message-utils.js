/**
 * Pure message rendering helpers shared by the web page and unit tests.
 *
 * Exposed as `window.WeMsgMessageUtils` in the browser and as a CommonJS
 * module under Node so the parsing rules can be tested without a DOM.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.WeMsgMessageUtils = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const QUOTE_TYPE = 244813135921;
  const EMOJI_RE = /\[([^\[\]]{1,4})\]/g;

  // WeChat emoji tokens are stored as [名称] in message content. The official
  // client renders local emoji images; we map them to their Unicode twins so
  // the page stays offline and text selection/copy keeps working.
  const WX_EMOJI = {
    "微笑": "😊",
    "撇嘴": "😣",
    "色": "😍",
    "发呆": "😳",
    "得意": "😎",
    "流泪": "😢",
    "害羞": "😳",
    "闭嘴": "🤐",
    "睡": "😴",
    "大哭": "😭",
    "尴尬": "😅",
    "发怒": "😡",
    "调皮": "😜",
    "呲牙": "😁",
    "惊讶": "😮",
    "难过": "😞",
    "酷": "😎",
    "冷汗": "😰",
    "抓狂": "😫",
    "吐": "🤮",
    "偷笑": "🤭",
    "可爱": "🥰",
    "白眼": "🙄",
    "傲慢": "😤",
    "饥饿": "🤤",
    "困": "😪",
    "惊恐": "😨",
    "流汗": "😓",
    "憨笑": "😄",
    "大兵": "\U0001fae1",
    "奋斗": "💪",
    "咒骂": "🤬",
    "疑问": "❓",
    "嘘": "🤫",
    "晕": "😵",
    "折磨": "😩",
    "衰": "😥",
    "骷髅": "💀",
    "敲打": "🔨",
    "再见": "👋",
    "擦汗": "😓",
    "抠鼻": "🤏",
    "鼓掌": "👏",
    "糗大了": "😳",
    "坏笑": "😏",
    "左哼哼": "😤",
    "右哼哼": "😤",
    "哈欠": "🥱",
    "鄙视": "😒",
    "委屈": "🥺",
    "快哭了": "🥺",
    "阴险": "😈",
    "亲亲": "😘",
    "吓": "😱",
    "可怜": "🥺",
    "菜刀": "🔪",
    "西瓜": "🍉",
    "啤酒": "🍺",
    "篮球": "🏀",
    "乒乓": "🏓",
    "咖啡": "☕",
    "饭": "🍚",
    "猪头": "🐷",
    "玫瑰": "🌹",
    "凋谢": "🥀",
    "示爱": "💗",
    "爱心": "❤️",
    "心碎": "💔",
    "蛋糕": "🎂",
    "闪电": "⚡",
    "炸弹": "💣",
    "刀": "🔪",
    "足球": "⚽",
    "瓢虫": "🐞",
    "便便": "💩",
    "月亮": "🌙",
    "太阳": "☀️",
    "礼物": "🎁",
    "拥抱": "🤗",
    "强": "👍",
    "弱": "👎",
    "握手": "🤝",
    "胜利": "✌️",
    "抱拳": "🙏",
    "勾引": "👆",
    "拳头": "✊",
    "差劲": "👎",
    "爱你": "🤟",
    "NO": "🙅",
    "OK": "👌",
    "爱情": "💑",
    "飞吻": "😘",
    "跳跳": "💃",
    "发抖": "🥶",
    "怄火": "😤",
    "转圈": "💫",
    "磕头": "🙇",
    "回头": "🔙",
    "跳绳": "🏃",
    "挥手": "👋",
    "激动": "🤩",
    "街舞": "💃",
    "献吻": "😘",
    "左太极": "☯️",
    "右太极": "☯️",
    "嘿哈": "😆",
    "捂脸": "🤦",
    "奸笑": "😏",
    "机智": "🤓",
    "皱眉": "😟",
    "耶": "✌️",
    "红包": "🧧",
    "鸡": "🐔",
    "Emm": "🤔",
    "加油": "💪",
    "汗": "😓",
    "天啊": "😱",
    "社会社会": "🤙",
    "旺柴": "🐕",
    "好的": "👌",
    "打脸": "🤦",
    "哇": "😲",
    "翻白眼": "🙄",
    "666": "👍",
    "让我看看": "👀",
    "叹气": "😮\u200d💨",
    "苦涩": "😣",
    "裂开": "💔",
    "嘴唇": "💋",
    "爱心": "❤️",
    "破涕为笑": "😂",
  };

  function detailOf(message) {
    if (!message) return {};
    let detail = message.detail_json;
    if (typeof detail === "string") {
      try {
        detail = JSON.parse(detail);
      } catch (_) {
        return {};
      }
    }
    return detail && typeof detail === "object" && !Array.isArray(detail)
      ? detail
      : {};
  }

  function richTextParts(text) {
    const value = String(text == null ? "" : text);
    const parts = [];
    let last = 0;
    EMOJI_RE.lastIndex = 0;
    let match = EMOJI_RE.exec(value);
    while (match) {
      const emoji = WX_EMOJI[match[1]];
      if (emoji) {
        if (match.index > last) {
          parts.push({ type: "text", value: value.slice(last, match.index) });
        }
        parts.push({ type: "emoji", value: emoji, name: match[1] });
        last = match.index + match[0].length;
      }
      match = EMOJI_RE.exec(value);
    }
    if (last < value.length) {
      parts.push({ type: "text", value: value.slice(last) });
    }
    if (!parts.length) {
      parts.push({ type: "text", value });
    }
    return parts;
  }

  function plainText(text) {
    return richTextParts(text)
      .map((part) => part.value)
      .join("");
  }

  function referSummary(refer) {
    const summary = String(refer.summary || "").trim();
    if (summary) return summary;
    const type = Number(refer.type) || 0;
    if (type === 3) return "[图片]";
    if (type === 43) return "[视频]";
    if (type === 34) return "[语音]";
    if (type === 49) return "[链接]";
    return "[消息]";
  }

  function parseQuote(message) {
    if (!message || Number(message.type) !== QUOTE_TYPE) return null;
    const detail = detailOf(message);
    const refer = detail.refer;
    if (!refer || typeof refer !== "object" || Array.isArray(refer)) return null;
    return {
      text: String(detail.text || ""),
      refer: {
        sender: String(refer.sender || "未知"),
        sender_wxid: String(refer.sender_wxid || ""),
        summary: referSummary(refer),
        type: Number(refer.type) || 0,
        subtype: Number(refer.subtype) || 0,
        svrid: refer.svrid == null ? "" : String(refer.svrid),
        time: Number(refer.time) || 0,
      },
    };
  }

  function idOf(value) {
    return value == null ? "" : String(value).trim();
  }

  /**
   * Locate the message a quote points at, inside the current conversation.
   *
   * `refer.svrid` is the original message's `server_id`. Both values pass
   * through JSON as 64-bit integers, so String() comparison is stable even
   * though JavaScript loses precision above Number.MAX_SAFE_INTEGER (the same
   * literal rounds to the same double on both sides).
   *
   * When server ids are missing (older snapshots), fall back to the refer's
   * sender, second-level timestamp and message type.
   */
  function findQuotedMessage(messages, quote) {
    if (!Array.isArray(messages) || !quote || !quote.refer) return null;
    const refer = quote.refer;
    const svrid = idOf(refer.svrid);
    if (svrid) {
      const matched = messages.find(
        (message) => message && idOf(message.server_id) === svrid
      );
      if (matched) return matched;
    }
    const referTime = Number(refer.time) || 0;
    if (!referTime) return null;
    const candidates = messages.filter((message) => {
      if (!message || Number(message.timestamp) !== referTime) return false;
      if (
        refer.sender_wxid &&
        message.sender_wxid &&
        String(message.sender_wxid) !== String(refer.sender_wxid)
      ) {
        return false;
      }
      if (refer.type && Number(message.type) !== Number(refer.type)) {
        return false;
      }
      return true;
    });
    return candidates.length ? candidates[candidates.length - 1] : null;
  }

  const FILE_CATEGORIES = [
    ["image", ["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"]],
    ["video", ["mp4", "mov", "m4v", "webm"]],
    ["audio", ["mp3", "wav", "m4a", "aac", "ogg", "flac"]],
    ["pdf", ["pdf"]],
    ["text", ["txt", "md", "json", "csv", "log", "xml", "yaml", "yml",
      "py", "js", "ts", "html", "css", "sh"]],
    ["office", ["doc", "docx", "xls", "xlsx", "ppt", "pptx"]],
    ["archive", ["zip", "rar", "7z", "tar", "gz", "bz2", "xz"]],
  ];

  function fileCategory(name) {
    const match = String(name || "").toLowerCase().match(/\.([^.]+)$/);
    if (!match) return "other";
    const extension = match[1];
    const found = FILE_CATEGORIES.find(([, extensions]) =>
      extensions.includes(extension)
    );
    return found ? found[0] : "other";
  }

  function imagePreviewUrl(media) {
    return (media && (media.original_url || media.url)) || null;
  }

  function previewText(message) {
    if (!message) return "暂无消息";
    const media = message.media || {};
    if (media.kind === "image") return "[图片]";
    if (media.kind === "video") return "[视频]";
    if (media.kind === "voice") return "[语音]";
    if (media.kind === "file") return `[文件] ${media.name || ""}`.trim();
    const type = Number(message.type);
    if (type === 3) return "[图片]";
    if (type === 43) return "[视频]";
    if (type === 34) return "[语音]";
    if (type === 10000) return plainText(message.content || "[系统消息]");
    const quote = parseQuote(message);
    const text = plainText(
      (quote && quote.text) || message.content || ""
    )
      .replace(/\s+/g, " ")
      .trim();
    return text.slice(0, 46) || `[${message.type_name || "消息"}]`;
  }

  return {
    WX_EMOJI,
    richTextParts,
    plainText,
    parseQuote,
    findQuotedMessage,
    fileCategory,
    imagePreviewUrl,
    previewText,
  };
});
