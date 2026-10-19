const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

test("account changes lock stale application data before revealing the new account", async () => {
  const events = [];
  let initialize;
  let authChanged;
  let nextApplication;
  const client = { auth: {
    onAuthStateChange(callback) { authChanged = callback; },
    getSession: async () => ({data: {session: {access_token: "one", user: {id: "one"}}}}),
  }};
  const context = vm.createContext({ console, Event, document: {
    getElementById: () => null,
    addEventListener(type, callback) { if (type === "DOMContentLoaded") initialize = callback; },
    dispatchEvent(event) { events.push(event.type); if (event.type === "classmood:ready") nextApplication?.(); },
  }, window: {location: {protocol: "http:", origin: "http://localhost"},
    supabase: {createClient: () => client}, setTimeout(callback) { callback(); }},
  fetch: async (url, options = {}) => ({ok: true, headers: {get: () => "application/json"},
    json: async () => url.endsWith("/api/config")
      ? {auth: {enabled: true, supabase_url: "https://example.invalid", publishable_key: "test"}}
      : {ok: true, user: {id: options.headers.Authorization.slice(7)}},
  }) });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "dashboard", "auth.js"), "utf8"), context);
  const ready = new Promise(resolve => { nextApplication = resolve; });
  initialize();
  await ready;
  assert.deepEqual(events, ["classmood:locked", "classmood:ready"]);
  events.length = 0;
  const sameAccount = new Promise(resolve => { nextApplication = resolve; });
  authChanged("TOKEN_REFRESHED", {access_token: "one", user: {id: "one"}});
  await sameAccount;
  assert.deepEqual(events, ["classmood:ready"]);
  events.length = 0;
  const otherAccount = new Promise(resolve => { nextApplication = resolve; });
  authChanged("SIGNED_IN", {access_token: "two", user: {id: "two"}});
  await otherAccount;
  assert.deepEqual(events, ["classmood:locked", "classmood:ready"]);
});
