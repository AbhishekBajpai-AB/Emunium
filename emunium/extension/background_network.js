(() => {
  "use strict";

  const scope = globalThis.EmuniumBackground;
  const BUFFER_SIZE = 50;

  const networkState = {
    recentResponses: [],
    pendingWaiters: [],
    idleWaiters: new Set(),
    inFlightByTab: new Map(),
    responseSequence: 0,
    requestSequence: 0,
    requestSequenceById: new Map(),
  };

  function matchesPattern(url, pattern) {
    const regex = new RegExp(
      "^" +
        pattern
          .replace(/[.+^${}()|[\]\\]/g, "\\$&")
          .replace(/\*/g, ".*") +
        "$"
    );
    return regex.test(url);
  }

  function notifyIdleWaiters(tabId) {
    for (const waiter of networkState.idleWaiters) {
      if (waiter.tabId === tabId) {
        waiter.check();
      }
    }
  }

  function addInFlightRequest(details) {
    if (details.tabId < 0) return;
    const requestSequence = ++networkState.requestSequence;
    networkState.requestSequenceById.set(details.requestId, requestSequence);
    let requests = networkState.inFlightByTab.get(details.tabId);
    if (!requests) {
      requests = new Set();
      networkState.inFlightByTab.set(details.tabId, requests);
    }
    requests.add(details.requestId);
    notifyIdleWaiters(details.tabId);
  }

  function finishInFlightRequest(details) {
    if (details.tabId < 0) return;
    networkState.requestSequenceById.delete(details.requestId);
    const requests = networkState.inFlightByTab.get(details.tabId);
    if (!requests) return;
    requests.delete(details.requestId);
    if (requests.size === 0) {
      networkState.inFlightByTab.delete(details.tabId);
    }
    notifyIdleWaiters(details.tabId);
  }

  function addResponse(details) {
    const entry = {
      sequence: ++networkState.responseSequence,
      requestSequence:
        networkState.requestSequenceById.get(details.requestId) ?? 0,
      url: details.url,
      statusCode: details.statusCode,
      method: details.method || "GET",
      type: details.type,
      timeStamp: details.timeStamp,
      tabId: details.tabId,
    };

    networkState.recentResponses.push(entry);
    if (networkState.recentResponses.length > BUFFER_SIZE) {
      networkState.recentResponses.shift();
    }

    const remaining = [];
    for (const waiter of networkState.pendingWaiters) {
      const tabMatches = waiter.tabId == null || waiter.tabId === entry.tabId;
      if (
        entry.requestSequence > waiter.sinceSequence &&
        tabMatches &&
        matchesPattern(entry.url, waiter.pattern)
      ) {
        clearTimeout(waiter.timeoutId);
        waiter.resolve(entry);
      } else {
        remaining.push(waiter);
      }
    }
    networkState.pendingWaiters = remaining;
  }

  function waitForResponse(pattern, timeoutMs, tabId, sinceSequence) {
    const marker = sinceSequence ?? networkState.requestSequence;
    const existing = networkState.recentResponses.find(
      (response) =>
        response.requestSequence > marker &&
        (tabId == null || response.tabId === tabId) &&
        matchesPattern(response.url, pattern)
    );
    if (existing) {
      return Promise.resolve(existing);
    }

    return new Promise((resolve) => {
      const waiter = { pattern, tabId, sinceSequence: marker, resolve };
      waiter.timeoutId = setTimeout(() => {
        const index = networkState.pendingWaiters.indexOf(waiter);
        if (index !== -1) {
          networkState.pendingWaiters.splice(index, 1);
          resolve(null);
        }
      }, timeoutMs);
      networkState.pendingWaiters.push(waiter);
    });
  }

  function waitForIdle(tabId, silenceMs, timeoutMs) {
    return new Promise((resolve) => {
      let settled = false;
      let quietTimer = null;
      const timeoutTimer = setTimeout(() => {
        finish({ success: false, error: "Timeout" });
      }, timeoutMs);

      function finish(result) {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutTimer);
        if (quietTimer !== null) clearTimeout(quietTimer);
        networkState.idleWaiters.delete(waiter);
        resolve(result);
      }

      const waiter = {
        tabId,
        check() {
          if (settled) return;
          if (quietTimer !== null) {
            clearTimeout(quietTimer);
            quietTimer = null;
          }
          const requests = networkState.inFlightByTab.get(tabId);
          if (!requests || requests.size === 0) {
            quietTimer = setTimeout(
              () => finish({ success: true }),
              silenceMs
            );
          }
        },
      };

      networkState.idleWaiters.add(waiter);
      waiter.check();
    });
  }

  function getResponseMarker() {
    return networkState.requestSequence;
  }

  function getRecentResponses() {
    return networkState.recentResponses.slice();
  }

  if (typeof chrome !== "undefined" && chrome.webRequest) {
    chrome.webRequest.onBeforeRequest.addListener(
      (details) => addInFlightRequest(details),
      { urls: ["<all_urls>"] }
    );
    chrome.webRequest.onCompleted.addListener(
      (details) => {
        addResponse(details);
        finishInFlightRequest(details);
      },
      { urls: ["<all_urls>"] }
    );
    chrome.webRequest.onErrorOccurred.addListener(
      (details) => finishInFlightRequest(details),
      { urls: ["<all_urls>"] }
    );
  }

  Object.assign(scope, {
    networkState,
    getRecentResponses,
    getResponseMarker,
    waitForIdle,
    waitForResponse,
  });
})();
