const test = require("node:test");
const assert = require("node:assert/strict");
const utils = require("../message-utils.js");

test("renders [破涕为笑] as its Unicode emoji", () => {
  assert.deepEqual(utils.richTextParts("有什么好副业求带[破涕为笑]"), [
    { type: "text", value: "有什么好副业求带" },
    { type: "emoji", value: "😂", name: "破涕为笑" },
  ]);
});

test("keeps unknown bracket tokens as plain text", () => {
  assert.deepEqual(utils.richTextParts("看这个[链接]和[未知表情]"), [
    { type: "text", value: "看这个[链接]和[未知表情]" },
  ]);
});

test("parses a quote reply from detail_json", () => {
  const message = {
    type: 244813135921,
    content: "哥，是图生视频？还是直接文生视频？（引用 不卡不舒服斯基 [10-16 20:33]: [视频]）",
    detail_json: JSON.stringify({
      text: "哥，是图生视频？还是直接文生视频？",
      refer: {
        summary: "[视频]",
        type: 43,
        svrid: 1234567890123,
        sender: "不卡不舒服斯基",
        sender_wxid: "zzydayong",
        time: 1792156434,
      },
    }),
  };
  assert.deepEqual(utils.parseQuote(message), {
    text: "哥，是图生视频？还是直接文生视频？",
    refer: {
      sender: "不卡不舒服斯基",
      sender_wxid: "zzydayong",
      summary: "[视频]",
      type: 43,
      subtype: 0,
      svrid: "1234567890123",
      time: 1792156434,
    },
  });
});

test("finds the quoted message by server id", () => {
  const messages = [
    { local_id: 1, server_id: 111, type: 1, timestamp: 1 },
    {
      local_id: 2,
      server_id: 5053359168659236148,
      type: 43,
      timestamp: 1792156434,
    },
  ];
  const quote = utils.parseQuote({
    type: 244813135921,
    detail_json: JSON.stringify({
      text: "回复",
      refer: {
        summary: "[视频]",
        type: 43,
        svrid: 5053359168659236148,
        sender: "不卡不舒服斯基",
        sender_wxid: "zzydayong",
        time: 1792156434,
      },
    }),
  });

  assert.equal(utils.findQuotedMessage(messages, quote).local_id, 2);
});

test("falls back to sender, time and type without server ids", () => {
  const messages = [
    {
      local_id: 7,
      type: 1,
      timestamp: 1792156434,
      sender_wxid: "wxid_a",
    },
    { local_id: 8, type: 43, timestamp: 1792156434, sender_wxid: "wxid_a" },
    { local_id: 9, type: 1, timestamp: 1792156434, sender_wxid: "wxid_b" },
  ];
  const quote = {
    refer: { type: 1, sender_wxid: "wxid_a", time: 1792156434 },
  };

  assert.equal(utils.findQuotedMessage(messages, quote).local_id, 7);
});

test("returns null when the quoted message is not in the conversation", () => {
  const messages = [{ local_id: 1, server_id: 111, timestamp: 2 }];
  assert.equal(
    utils.findQuotedMessage(messages, { refer: { svrid: "999", time: 1 } }),
    null
  );
  assert.equal(utils.findQuotedMessage(messages, null), null);
});

test("does not treat a normal text message as a quote", () => {
  assert.equal(
    utils.parseQuote({ type: 1, content: "普通消息", detail_json: "{}" }),
    null
  );
  assert.equal(
    utils.parseQuote({ type: 244813135921, detail_json: "{broken" }),
    null
  );
});

test("preview uses the reply body and converts emoji tokens", () => {
  const quote = {
    type: 244813135921,
    detail_json: JSON.stringify({
      text: "我这个呢[破涕为笑]",
      refer: { summary: "怎么做的？", type: 1, sender: "何镜泉" },
    }),
  };
  assert.equal(utils.previewText(quote), "我这个呢😂");
  assert.equal(
    utils.previewText({ type: 1, content: "求带[破涕为笑]" }),
    "求带😂"
  );
});

test("classifies local file attachments by extension", () => {
  assert.equal(utils.fileCategory("报表(2).xlsx"), "office");
  assert.equal(utils.fileCategory("需求.docx"), "office");
  assert.equal(utils.fileCategory("改.rar"), "archive");
  assert.equal(utils.fileCategory("图片.PNG"), "image");
  assert.equal(utils.fileCategory("说明.txt"), "text");
  assert.equal(utils.fileCategory("演示.pdf"), "pdf");
  assert.equal(utils.fileCategory("apk.1.1.1"), "other");
  assert.equal(utils.fileCategory(""), "other");
});

test("image lightbox prefers the original over the thumbnail", () => {
  assert.equal(
    utils.imagePreviewUrl({ url: "/thumb.jpg", original_url: "/full.jpg" }),
    "/full.jpg"
  );
  assert.equal(utils.imagePreviewUrl({ url: "/thumb.jpg" }), "/thumb.jpg");
  assert.equal(utils.imagePreviewUrl(null), null);
});

test("preview keeps WeChat media labels", () => {
  assert.equal(
    utils.previewText({ type: 43, media: { kind: "video", duration: 30 } }),
    "[视频]"
  );
  assert.equal(utils.previewText({ type: 3 }), "[图片]");
});
