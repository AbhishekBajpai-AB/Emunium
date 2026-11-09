const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadNetworkModule() {
  const listeners = {};
  const scope = {};
  const makeEvent = (name) => ({
    addListener(callback) {
      listeners[name] = callback;
    },
  });
  const chrome = {
    webRequest: {
      onBeforeRequest: makeEvent("before"),
      onCompleted: makeEvent("completed"),
      onErrorOccurred: makeEvent("error"),
    },
  };
  const context = { chrome, setTimeout, clearTimeout };
  context.globalThis = context;
  context.EmuniumBackground = scope;
  const source = fs.readFileSync(
    path.join(__dirname, "..", "emunium", "extension", "background_network.js"),
    "utf8"
  );
  vm.runInNewContext(source, context);
  return { listeners, scope };
}

function request(listeners, requestId, tabId, url) {
  listeners.before({ requestId, tabId, url });
  listeners.completed({
    requestId,
    tabId,
    url,
    method: "GET",
    statusCode: 200,
    timeStamp: Date.now(),
    type: "xmlhttprequest",
  });
}

test("response wait ignores earlier responses and scopes to a tab", async () => {
  const { listeners, scope } = loadNetworkModule();
  request(listeners, "old", 7, "https://example.test/api/users");
  const marker = scope.getResponseMarker();
  const waiting = scope.waitForResponse("*/api/users", 500, 7, marker);

  request(listeners, "other-tab", 8, "https://example.test/api/users");
  request(listeners, "new", 7, "https://example.test/api/users");

  const response = await waiting;
  assert.equal(response.url, "https://example.test/api/users");
  assert.equal(response.tabId, 7);
  assert.equal(response.requestSequence > marker, true);
});

test("network idle waits for requests to finish and stay quiet", async () => {
  const { listeners, scope } = loadNetworkModule();
  listeners.before({ requestId: "slow", tabId: 3, url: "https://example.test/slow" });
  const idle = scope.waitForIdle(3, 20, 500);

  setTimeout(() => {
    listeners.completed({
      requestId: "slow",
      tabId: 3,
      url: "https://example.test/slow",
      method: "GET",
      statusCode: 200,
      timeStamp: Date.now(),
      type: "xmlhttprequest",
    });
  }, 10);

  const result = await idle;
  assert.equal(result.success, true);
});

test("network idle returns false when a request exceeds the timeout", async () => {
  const { listeners, scope } = loadNetworkModule();
  listeners.before({ requestId: "stuck", tabId: 4, url: "https://example.test/stuck" });
  const result = await scope.waitForIdle(4, 0, 20);
  assert.equal(result.success, false);
  assert.equal(result.error, "Timeout");
});
