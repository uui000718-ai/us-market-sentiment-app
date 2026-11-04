import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server renders the Market Pulse application", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /Market Pulse/);
  assert.match(html, /美股情绪决策/);
  assert.match(html, /manifest\.webmanifest/);
  assert.doesNotMatch(html, /Your site is taking shape|codex-preview/);
});

test("PWA files and live-data endpoint are wired", async () => {
  const [page, manifest, serviceWorker, route] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"),
    readFile(new URL("../public/sw.js", import.meta.url), "utf8"),
    readFile(new URL("../app/api/report/route.ts", import.meta.url), "utf8"),
  ]);

  assert.match(page, /\/api\/report/);
  assert.match(page, /localStorage/);
  assert.match(page, /serviceWorker/);
  assert.equal(JSON.parse(manifest).display, "standalone");
  assert.match(serviceWorker, /market-pulse/);
  assert.match(route, /SENTIMENT_DATA_URL/);
  assert.match(route, /status:\s*503/);
  assert.doesNotMatch(route, /demoReport|delivery_mode:\s*"preview"/);
});

test("upstream failure returns 503 instead of a simulated investment recommendation", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("unavailable", { status: 502 });
  try {
    const response = await render("/api/report");
    assert.equal(response.status, 503);
    const payload = await response.json();
    assert.equal(payload.decision, undefined);
    assert.equal(payload.delivery_mode, undefined);
    assert.match(response.headers.get("cache-control"), /no-store/);
  } finally { globalThis.fetch = original; }
});

test("optional module failure preserves a valid core report", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (input) => {
    if (String(input).includes("latest.json")) return Response.json({
      mode: "live", generated_at: "2026-11-04T22:00:00Z", market_date: "2026-11-04",
      indicators: [{ name: "vix", value: "17.0", detail: "行情日期 2026-11-04", score: 75 }],
      decision: { score: 0, recommendation: "观望", triggers: [], suppressed_signals: [] },
    });
    return new Response("unavailable", { status: 502 });
  };
  try {
    const response = await render("/api/report");
    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.equal(payload.delivery_mode, "live");
    assert.equal(payload.decision.recommendation, "观望");
    assert.equal(payload.dca, null);
    assert.equal(payload.premiums, null);
    assert.equal(payload.module_errors.length, 2);
  } finally { globalThis.fetch = original; }
});
