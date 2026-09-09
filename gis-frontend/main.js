const { app, BrowserWindow, Menu } = require('electron');
const http = require('http');

function createWindow() {
  const win = new BrowserWindow({
    width: 1000,
    height: 800,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });
  win.loadFile('index.html');
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null); // Disable default menu bar
  createWindow();
});

app.on('window-all-closed', () => {
  // Send POST /shutdown to stop the local FastAPI server
  const req = http.request({
    hostname: '127.0.0.1',
    port: 8000,
    path: '/shutdown',
    method: 'POST'
  }, () => {
    app.quit();
  });

  req.on('error', () => {
    app.quit(); // Always quit Electron, even if server was already down
  });

  req.end();
});
