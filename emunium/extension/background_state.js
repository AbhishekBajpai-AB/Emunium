(() => {
  "use strict";

  const scope = (globalThis.EmuniumBackground = globalThis.EmuniumBackground || {});
  const state = scope.state || {
    ws: null,
    wsUrl: null,
    reconnectTimer: null,
    connecting: false,
    readyTabs: new Set(),
    tabDocIds: new Map(),
    pinnedTabId: null,
  };

  async function getPort() {
    try {
      const response = await fetch(
        chrome.runtime.getURL("port.json") + "?t=" + Date.now(),
        { cache: "no-store" }
      );
      if (response.ok) {
        const data = await response.json();
        const host = data.host || "127.0.0.1";
        const isIPv4Loopback = /^127(?:\.\d{1,3}){3}$/.test(host) &&
          host.split(".").every((part) => Number(part) <= 255);
        if (
          Number.isInteger(data.port) &&
          data.port > 0 &&
          data.port <= 65535 &&
          (isIPv4Loopback || host === "::1") &&
          typeof data.token === "string" &&
          /^[A-Za-z0-9_-]{40,50}$/.test(data.token)
        ) {
          return { host, port: data.port, token: data.token };
        }
      }
    } catch {}
    return null;
  }

  function clearReconnect() {
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
  }

  function clearKeepAlive(socket) {
    if (socket && socket._keepAlive) {
      clearInterval(socket._keepAlive);
      socket._keepAlive = null;
    }
  }

  function startKeepAlive(socket) {
    clearKeepAlive(socket);
    socket._keepAlive = setInterval(() => {
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ event: "ping" }));
      }
    }, 20000);
  }

  function clearTrackedTab(tabId) {
    state.readyTabs.delete(tabId);
    state.tabDocIds.delete(tabId);
  }

  function clearPinnedTab(tabId) {
    if (state.pinnedTabId === tabId) {
      state.pinnedTabId = null;
    }
  }

  function scheduleReconnect(delay) {
    if (state.reconnectTimer) {
      return;
    }
    state.reconnectTimer = setTimeout(() => {
      state.reconnectTimer = null;
      connect();
    }, delay);
  }

  async function connect() {
    if (state.connecting || (state.ws && (
      state.ws.readyState === WebSocket.OPEN ||
      state.ws.readyState === WebSocket.CONNECTING
    ))) {
      return;
    }
    state.connecting = true;
    try {
      const config = await getPort();
      if (!config) {
        scheduleReconnect(2000);
        return;
      }

      const host = config.host === "::1" ? "[::1]" : config.host;
      state.wsUrl = `ws://${host}:${config.port}/bridge/${encodeURIComponent(config.token)}`;
      try {
        state.ws = new WebSocket(state.wsUrl);
      } catch {
        state.ws = null;
        scheduleReconnect(2000);
        return;
      }

      if (typeof scope.attachSocketHandlers === "function") {
        scope.attachSocketHandlers(state.ws);
      }
    } finally {
      state.connecting = false;
    }
  }

  function send(data) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(data));
    }
  }

  async function getActiveTabId() {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    return tab?.id || null;
  }

  function waitForContentReady(tabId, timeout = 5000) {
    if (state.readyTabs.has(tabId)) {
      return Promise.resolve(true);
    }
    return new Promise((resolve) => {
      let settled = false;
      const intervalId = setInterval(() => {
        if (!settled && state.readyTabs.has(tabId)) {
          settled = true;
          clearInterval(intervalId);
          clearTimeout(timeoutId);
          resolve(true);
        }
      }, 50);
      const timeoutId = setTimeout(() => {
        if (!settled) {
          settled = true;
          clearInterval(intervalId);
          resolve(state.readyTabs.has(tabId));
        }
      }, timeout);
    });
  }

  async function sendToContentScript(tabId, msg, frameId) {
    const maxAttempts = 3;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        const options = { frameId };
        const documentId = state.tabDocIds.get(tabId);
        if (documentId) {
          options.documentId = documentId;
        }
        return await chrome.tabs.sendMessage(
          tabId,
          { __emunium__: true, ...msg },
          options
        );
      } catch (error) {
        clearTrackedTab(tabId);
        if (attempt < maxAttempts - 1) {
          await waitForContentReady(tabId, 5000);
          continue;
        }
        return {
          id: msg.id,
          result: { error: "Content script error: " + error.message },
        };
      }
    }

    return {
      id: msg.id,
      result: { error: "Content script error: max retries exceeded" },
    };
  }

  async function resolveTabId(msg) {
    return (
      msg.tabId ||
      msg.params?.tabId ||
      state.pinnedTabId ||
      (await getActiveTabId())
    );
  }

  Object.assign(scope, {
    state,
    clearKeepAlive,
    clearPinnedTab,
    clearReconnect,
    clearTrackedTab,
    connect,
    getActiveTabId,
    resolveTabId,
    scheduleReconnect,
    send,
    sendToContentScript,
    startKeepAlive,
    waitForContentReady,
  });
})();
