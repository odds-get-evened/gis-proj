const { app, BrowserWindow, Menu, dialog } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

// Must match HOST/PORT in main.py and the URLs used in index.html
const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 8000;

/** Minimal HTTP client for talking to the local FastAPI backend. */
class BackendClient {
  constructor(host, port) {
    this.host = host;
    this.port = port;
  }

  /** Resolves with the HTTP status code, or rejects on connection error/timeout. */
  request(method, urlPath, timeoutMs = 2000) {
    return new Promise((resolve, reject) => {
      const req = http.request(
        { hostname: this.host, port: this.port, path: urlPath, method, timeout: timeoutMs },
        (res) => {
          res.resume(); // drain the body; only the status matters here
          resolve(res.statusCode);
        }
      );
      req.on('timeout', () => req.destroy(new Error('Request timed out')));
      req.on('error', reject);
      req.end();
    });
  }

  async isHealthy() {
    try {
      return (await this.request('GET', '/health', 1000)) === 200;
    } catch {
      return false;
    }
  }

  async requestShutdown() {
    try {
      await this.request('POST', '/shutdown');
    } catch {
      // Backend already gone; nothing to do
    }
  }
}

/**
 * Owns the lifecycle of the Python backend.
 * Packaged builds launch the bundled PyInstaller executable; in development
 * the backend is started separately by `npm run dev`, so nothing is spawned.
 */
class BackendProcess {
  constructor(client) {
    this.client = client;
    this.child = null;
  }

  get executablePath() {
    const name = process.platform === 'win32' ? 'gis-backend.exe' : 'gis-backend';
    return path.join(process.resourcesPath, 'bin', 'gis-backend', name);
  }

  get logFilePath() {
    return path.join(app.getPath('logs'), 'backend.log');
  }

  start() {
    if (!app.isPackaged) return;

    const exe = this.executablePath;
    if (!fs.existsSync(exe)) {
      throw new Error(`Backend executable not found at:\n${exe}`);
    }

    fs.mkdirSync(path.dirname(this.logFilePath), { recursive: true });
    const log = fs.openSync(this.logFilePath, 'a');

    this.child = spawn(exe, [], {
      cwd: path.dirname(exe),
      stdio: ['ignore', log, log],
      windowsHide: true, // no console window on Windows
    });
    this.child.on('exit', (code) => {
      console.log(`Backend exited with code ${code}`);
      this.child = null;
    });
  }

  get isRunning() {
    return this.child !== null && this.child.exitCode === null;
  }

  /** Polls /health until the backend answers, or throws after timeoutMs. */
  async waitUntilReady(timeoutMs = 30000, intervalMs = 250) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await this.client.isHealthy()) return;
      if (app.isPackaged && !this.isRunning) {
        throw new Error(`The backend stopped unexpectedly.\nSee the log at:\n${this.logFilePath}`);
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error(
      app.isPackaged
        ? `The backend did not start within ${timeoutMs / 1000} seconds.\nSee the log at:\n${this.logFilePath}`
        : `No backend is answering on ${BACKEND_HOST}:${BACKEND_PORT}. Start the app with "npm run dev".`
    );
  }

  /** Asks the backend to shut down gracefully, and force-kills it if it doesn't. */
  async stop(graceMs = 3000) {
    await this.client.requestShutdown();
    if (!this.isRunning) return;

    await new Promise((resolve) => {
      const timer = setTimeout(() => {
        if (this.isRunning) this.child.kill();
        resolve();
      }, graceMs);
      this.child.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }
}

/** Top-level application: starts the backend, opens the window, cleans up on quit. */
class GisLookupApp {
  constructor() {
    this.backend = new BackendProcess(new BackendClient(BACKEND_HOST, BACKEND_PORT));
    this.backendStopped = false;
  }

  run() {
    app.whenReady().then(() => this.onReady());
    app.on('window-all-closed', () => app.quit());
    app.on('will-quit', (event) => this.onWillQuit(event));
  }

  async onReady() {
    Menu.setApplicationMenu(null); // Disable default menu bar
    try {
      this.backend.start();
      await this.backend.waitUntilReady();
    } catch (error) {
      dialog.showErrorBox('NYS GIS Lookup could not start', error.message);
      app.quit();
      return;
    }
    this.createWindow();
  }

  createWindow() {
    const win = new BrowserWindow({
      width: 1000,
      height: 800,
      webPreferences: {
        nodeIntegration: true,
        contextIsolation: false,
      },
    });
    win.loadFile('index.html');
  }

  onWillQuit(event) {
    if (this.backendStopped) return;
    event.preventDefault(); // hold the quit until the backend is down
    this.backend.stop().finally(() => {
      this.backendStopped = true;
      app.quit();
    });
  }
}

new GisLookupApp().run();
