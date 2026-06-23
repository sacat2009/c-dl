const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("cdl", {
  selectDownloadFolder: (currentPath) => ipcRenderer.invoke("select-download-folder", currentPath),
  minimize: () => ipcRenderer.send("window:minimize"),
  maximize: () => ipcRenderer.send("window:maximize"),
  close: () => ipcRenderer.send("window:close"),
});
