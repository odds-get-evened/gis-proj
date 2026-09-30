const { app, BrowserWindow, Menu, dialog } = require('electron');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

// Must match HOST/PORT in main.py and the URLs used in index.html
const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 8000;

// Packages the backend needs when running from source (see README)
const BACKEND_PACKAGES = ['fastapi', 'uvicorn', 'requests', 'pydantic'];

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
 * Packaged builds launch the bundled PyInstaller executable. When running from
 * source, it finds a Python interpreter with the backend packages installed and
 * runs main.py with it, so no command needs to be on the PATH.
 */
class BackendProcess {
  constructor(client) {
    this.client = client;
    this.child = null;
    this.spawned = false;
  }

  get executablePath() {
    const name = process.platform === 'win32' ? 'gis-backend.exe' : 'gis-backend';
    return path.join(process.resourcesPath, 'bin', 'gis-backend', name);
  }

  get logFilePath() {
    return path.join(app.getPath('logs'), 'backend.log');
  }

  /** The repository root, where main.py lives, when running from source. */
  get sourceRoot() {
    return path.join(__dirname, '..');
  }

  async start() {
    if (await this.client.isHealthy()) {
      console.log('A backend is already running; using it.');
      return;
    }
    if (app.isPackaged) {
      this.startPackaged();
    } else {
      this.startFromSource();
    }
  }

  startPackaged() {
    const exe = this.executablePath;
    if (!fs.existsSync(exe)) {
      throw new Error(`Backend executable not found at:\n${exe}`);
    }

    fs.mkdirSync(path.dirname(this.logFilePath), { recursive: true });
    const log = fs.openSync(this.logFilePath, 'a');

    this.launch(exe, [], {
      cwd: path.dirname(exe),
      stdio: ['ignore', log, log],
    });
  }

  startFromSource() {
    const python = this.findPython();
    console.log(`Starting backend with: ${python} main.py`);
    this.launch(python, ['main.py'], {
      cwd: this.sourceRoot,
      stdio: 'inherit', // backend logs appear in the npm run dev terminal
    });
  }

  launch(command, args, options) {
    this.child = spawn(command, args, { ...options, windowsHide: true });
    this.spawned = true;
    this.child.on('error', (error) => console.error(`Could not start backend: ${error.message}`));
    this.child.on('exit', (code) => {
      console.log(`Backend exited with code ${code}`);
      this.child = null;
    });
  }

  /**
   * Returns the first Python interpreter that can import every backend package.
   * The GIS_PYTHON environment variable overrides the search.
   */
  findPython() {
    const candidates = process.env.GIS_PYTHON
      ? [process.env.GIS_PYTHON]
      : process.platform === 'win32'
        ? ['python', 'py', 'python3'] // 'py' is the Windows Python launcher
        : ['python3', 'python'];

    const check = `import ${BACKEND_PACKAGES.join(', ')}`;
    let foundPythonWithoutPackages = null;

    for (const candidate of candidates) {
      const result = spawnSync(candidate, ['-c', check], { windowsHide: true, encoding: 'utf8' });
      if (result.error) continue; // not installed / not on PATH
      if (result.status === 0) return candidate;
      if (/ModuleNotFoundError/.test(result.stderr || '')) foundPythonWithoutPackages ??= candidate;
    }

    if (foundPythonWithoutPackages) {
      throw new Error(
        `Python was found, but the backend packages aren't installed for it. Run:\n\n` +
        `${foundPythonWithoutPackages} -m pip install ${BACKEND_PACKAGES.join(' ')}`
      );
    }
    throw new Error(
      `No Python interpreter was found (tried: ${candidates.join(', ')}).\n\n` +
      `Install Python 3.12+, or set the GIS_PYTHON environment variable to the full path of python.exe.`
    );
  }

  get isRunning() {
    return this.child !== null && this.child.exitCode === null;
  }

  /** Polls /health until the backend answers, or throws after timeoutMs. */
  async waitUntilReady(timeoutMs = 30000, intervalMs = 250) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await this.client.isHealthy()) return;
      if (this.spawned && !this.isRunning) {
        throw new Error(
          app.isPackaged
            ? `The backend stopped unexpectedly.\nSee the log at:\n${this.logFilePath}`
            : 'The backend stopped unexpectedly. See the npm run dev terminal for the error.'
        );
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error(
      app.isPackaged
        ? `The backend did not start within ${timeoutMs / 1000} seconds.\nSee the log at:\n${this.logFilePath}`
        : `The backend did not start within ${timeoutMs / 1000} seconds. See the npm run dev terminal for details.`
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
      await this.backend.start();
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
