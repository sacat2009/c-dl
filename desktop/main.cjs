const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");

const isPackaged = app.isPackaged;
const root = isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
const appRoot = isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
const host = "127.0.0.1";
const port = Number(process.env.YTDLP_UI_PORT || 8765);
const url = `http://${host}:${port}`;
const python = path.join(appRoot, ".venv", "Scripts", "python.exe");
const backendExe = path.join(appRoot, "backend", "backend.exe");
const legacyBackendExe = path.join(appRoot, "backend.exe");
const logo = path.join(appRoot, "static", "assets", "logo.png");

let backend = null;
let ownsBackend = false;
let mainWindow = null;

function request(pathname = "/") {
  return new Promise((resolve) => {
    const req = http.get(`${url}${pathname}`, (res) => {
      res.resume();
      resolve(res.statusCode || 0);
    });
    req.on("error", () => resolve(0));
    req.setTimeout(700, () => {
      req.destroy();
      resolve(0);
    });
  });
}

async function waitForBackend() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const status = await request("/");
    if (status === 200) return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

async function ensureBackend() {
  if ((await request("/")) === 200) return;

  const backendCommand = isPackaged ? (require("fs").existsSync(backendExe) ? backendExe : legacyBackendExe) : python;
  const backendArgs = isPackaged ? [] : ["app.py"];
  backend = spawn(backendCommand, backendArgs, {
    cwd: root,
    env: {
      ...process.env,
      YTDLP_UI_NO_BROWSER: "1",
      YTDLP_UI_PORT: String(port),
      CDL_CONFIG_DIR: app.getPath("userData"),
      CDL_STATIC_DIR: path.join(appRoot, "static"),
    },
    windowsHide: true,
    stdio: "ignore",
  });
  ownsBackend = true;

  const ok = await waitForBackend();
  if (!ok) {
    throw new Error("Python 後端沒有成功啟動。請確認 .venv 與 yt-dlp 已安裝。");
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1220,
    height: 900,
    minWidth: 900,
    minHeight: 700,
    title: "C DL",
    frame: false,
    backgroundColor: "#080a0f",
    icon: logo,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.webContents.setWindowOpenHandler(({ url: nextUrl }) => {
    shell.openExternal(nextUrl);
    return { action: "deny" };
  });
  mainWindow.loadURL(url);
}

ipcMain.handle("select-download-folder", async (_event, currentPath) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "選擇下載位置",
    defaultPath: currentPath || app.getPath("downloads"),
    properties: ["openDirectory", "createDirectory"],
  });
  if (result.canceled || !result.filePaths.length) return "";
  return result.filePaths[0];
});

ipcMain.on("window:minimize", () => mainWindow?.minimize());
ipcMain.on("window:maximize", () => {
  if (!mainWindow) return;
  if (mainWindow.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow.maximize();
  }
});
ipcMain.on("window:close", () => mainWindow?.close());

app.whenReady().then(async () => {
  app.setName("C DL");
  try {
    await ensureBackend();
    createWindow();
  } catch (error) {
    dialog.showErrorBox("啟動失敗", error.message);
    app.quit();
  }
});

app.on("window-all-closed", () => {
  if (ownsBackend && backend && !backend.killed) {
    backend.kill();
  }
  app.quit();
});
