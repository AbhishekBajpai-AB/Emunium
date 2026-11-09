const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadConditions() {
  const scope = {};
  const style = {
    visibility: "visible",
    opacity: "1",
    pointerEvents: "auto",
    getPropertyValue: () => "",
  };
  const context = {
    document: { elementFromPoint: () => null },
    getComputedStyle: () => style,
    window: { getComputedStyle: () => style },
  };
  context.globalThis = context;
  context.EmuniumContent = scope;
  const source = fs.readFileSync(
    path.join(__dirname, "..", "emunium", "extension", "content_conditions.js"),
    "utf8"
  );
  vm.runInNewContext(source, context);
  return scope;
}

function element() {
  return {
    offsetWidth: 100,
    offsetHeight: 20,
    disabled: false,
    isConnected: true,
    innerText: "ready",
    textContent: "ready",
    classList: { contains: () => false },
    hasAttribute: () => false,
    getAttribute: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 20 }),
    contains: () => false,
  };
}

test("nested stable conditions wait for their requested duration", () => {
  const scope = loadConditions();
  const target = element();
  const conditions = [
    {
      type: "all_of",
      conditions: [[{ type: "visible" }, { type: "stable", duration: 500 }]],
    },
  ];

  assert.equal(scope.checkElementConditions(target, null, conditions, [target], 100), false);
  assert.equal(scope.checkElementConditions(target, null, conditions, [target], 500), true);
});

test("stable in an OR branch does not delay another satisfied branch", () => {
  const scope = loadConditions();
  const target = element();
  const conditions = [
    {
      type: "any_of",
      conditions: [
        [{ type: "stable", duration: 500 }],
        [{ type: "visible" }],
      ],
    },
  ];

  assert.equal(scope.checkElementConditions(target, null, conditions, [target], 0), true);
});

test("negated stable condition uses the current stable duration", () => {
  const scope = loadConditions();
  const target = element();
  const conditions = [
    { type: "not", condition: [{ type: "stable", duration: 300 }] },
  ];

  assert.equal(scope.checkElementConditions(target, null, conditions, [target], 0), true);
  assert.equal(scope.checkElementConditions(target, null, conditions, [target], 300), false);
});

test("waitForSelector honors stable nested in all_of", async () => {
  const scope = loadConditions();
  const target = {
    isConnected: true,
    innerText: "ready",
    textContent: "ready",
    href: null,
    value: null,
    getBoundingClientRect: () => ({ x: 0, y: 0, width: 100, height: 20 }),
  };
  scope.getElementText = (node) => node.innerText;
  scope.serializeElement = (node) => ({ text: node.innerText });

  class MutationObserverStub {
    observe() {}
    disconnect() {}
  }

  const context = {
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    document: {
      querySelector: () => target,
      querySelectorAll: () => [target],
      documentElement: {},
      readyState: "complete",
      title: "test",
    },
    location: { href: "https://example.test" },
    MutationObserver: MutationObserverStub,
  };
  context.globalThis = context;
  context.EmuniumContent = scope;
  const source = fs.readFileSync(
    path.join(__dirname, "..", "emunium", "extension", "content_wait.js"),
    "utf8"
  );
  vm.runInNewContext(source, context);

  const startedAt = Date.now();
  const result = await scope.waitForSelector({
    selector: "#target",
    timeout: 1000,
    conditions: [
      {
        type: "all_of",
        conditions: [[{ type: "stable", duration: 80 }]],
      },
    ],
  });

  assert.equal(result.text, "ready");
  assert.equal(Date.now() - startedAt >= 70, true);
});
