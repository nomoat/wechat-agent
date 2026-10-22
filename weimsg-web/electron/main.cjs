const { app, BrowserWindow, shell } = require("electron");
const fs = require("fs");
const path = require("path");

function loadBuildConfig() {
  try {
    return JSON.parse(
      fs.readFileSync(path.join(__dirname, "config.json"), "utf8")
    );
  } catch (_) {
    return {};
  }
}

const buildConfig = loadBuildConfig();
const WEB_UI_URL =
  process.env.WEB_UI_URL || buildConfig.webUiUrl || "http://127.0.0.1:8080";

function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    title: "WeMsg Pilot",
    backgroundColor: "#f5f5f5",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });

  window.loadURL(WEB_UI_URL);

  window.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  window.webContents.on("did-fail-load", (_event, code, description) => {
    window.loadFile(path.join(__dirname, "offline.html"), {
      query: { url: WEB_UI_URL, code: String(code), description },
    });
  });
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
