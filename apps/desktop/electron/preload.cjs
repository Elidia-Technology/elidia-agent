const { contextBridge, ipcRenderer, webUtils } = require('electron')

contextBridge.exposeInMainWorld('elidiaDesktop', {
  getConnection: () => ipcRenderer.invoke('elidia:connection'),
  getBootProgress: () => ipcRenderer.invoke('elidia:boot-progress:get'),
  getConnectionConfig: () => ipcRenderer.invoke('elidia:connection-config:get'),
  saveConnectionConfig: payload => ipcRenderer.invoke('elidia:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('elidia:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('elidia:connection-config:test', payload),
  api: request => ipcRenderer.invoke('elidia:api', request),
  notify: payload => ipcRenderer.invoke('elidia:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('elidia:requestMicrophoneAccess'),
  readFileDataUrl: filePath => ipcRenderer.invoke('elidia:readFileDataUrl', filePath),
  readFileText: filePath => ipcRenderer.invoke('elidia:readFileText', filePath),
  selectPaths: options => ipcRenderer.invoke('elidia:selectPaths', options),
  writeClipboard: text => ipcRenderer.invoke('elidia:writeClipboard', text),
  saveImageFromUrl: url => ipcRenderer.invoke('elidia:saveImageFromUrl', url),
  saveImageBuffer: (data, ext) => ipcRenderer.invoke('elidia:saveImageBuffer', { data, ext }),
  saveClipboardImage: () => ipcRenderer.invoke('elidia:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('elidia:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('elidia:watchPreviewFile', url),
  stopPreviewFileWatch: id => ipcRenderer.invoke('elidia:stopPreviewFileWatch', id),
  setTitleBarTheme: payload => ipcRenderer.send('elidia:titlebar-theme', payload),
  setPreviewShortcutActive: active => ipcRenderer.send('elidia:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('elidia:openExternal', url),
  fetchLinkTitle: url => ipcRenderer.invoke('elidia:fetchLinkTitle', url),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('elidia:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('elidia:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('elidia:setting:defaultProjectDir:pick')
  },
  revealLogs: () => ipcRenderer.invoke('elidia:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('elidia:logs:recent'),
  readDir: dirPath => ipcRenderer.invoke('elidia:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('elidia:fs:gitRoot', startPath),
  terminal: {
    dispose: id => ipcRenderer.invoke('elidia:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('elidia:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('elidia:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('elidia:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `elidia:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)
      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `elidia:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)
      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('elidia:close-preview-requested', listener)
    return () => ipcRenderer.removeListener('elidia:close-preview-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('elidia:open-updates', listener)
    return () => ipcRenderer.removeListener('elidia:open-updates', listener)
  },
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('elidia:window-state-changed', listener)
    return () => ipcRenderer.removeListener('elidia:window-state-changed', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('elidia:preview-file-changed', listener)
    return () => ipcRenderer.removeListener('elidia:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('elidia:backend-exit', listener)
    return () => ipcRenderer.removeListener('elidia:backend-exit', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('elidia:power-resume', listener)
    return () => ipcRenderer.removeListener('elidia:power-resume', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('elidia:boot-progress', listener)
    return () => ipcRenderer.removeListener('elidia:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.cjs (apps/desktop/electron/bootstrap-runner.cjs).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('elidia:bootstrap:get'),
  resetBootstrap: () => ipcRenderer.invoke('elidia:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('elidia:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('elidia:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('elidia:bootstrap:event', listener)
    return () => ipcRenderer.removeListener('elidia:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('elidia:version'),
  updates: {
    check: () => ipcRenderer.invoke('elidia:updates:check'),
    apply: opts => ipcRenderer.invoke('elidia:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('elidia:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('elidia:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('elidia:updates:progress', listener)
      return () => ipcRenderer.removeListener('elidia:updates:progress', listener)
    }
  }
})
