const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("weimsg", {
  app: "WeMsg Pilot",
  version: "1.0.0",
});
