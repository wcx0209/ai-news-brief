const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer"
};

const TOPICS = new Set(["correction", "source", "product", "other"]);
const TOPIC_LABELS = {
  correction: "Story correction",
  source: "Source suggestion",
  product: "Website suggestion",
  other: "Other"
};

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: JSON_HEADERS });
}

function clean(value, max) {
  return String(value || "").replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "").trim().slice(0, max);
}

async function rateLimit(request) {
  try {
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const hour = new Date().toISOString().slice(0, 13);
    const bytes = new TextEncoder().encode(`${ip}:${hour}:polyemergence-feedback`);
    const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(byte => byte.toString(16).padStart(2, "0")).join("");
    const key = new Request(`https://feedback-rate.invalid/${digest}`);
    const cache = caches.default;
    const prior = await cache.match(key);
    const count = Number(await prior?.text() || 0);
    if (count >= 5) return false;
    await cache.put(key, new Response(String(count + 1), { headers: { "Cache-Control": "max-age=3600" } }));
    return true;
  } catch {
    return true;
  }
}

export async function onRequestPost({ request, env }) {
  const requestUrl = new URL(request.url);
  const origin = request.headers.get("Origin");
  try {
    if (origin && new URL(origin).host !== requestUrl.host) return json({ ok: false, error: "Forbidden" }, 403);
  } catch {
    return json({ ok: false, error: "Forbidden" }, 403);
  }
  if (Number(request.headers.get("Content-Length") || 0) > 10000) return json({ ok: false, error: "Payload too large" }, 413);

  let payload;
  try {
    const body = await request.text();
    if (body.length > 10000) return json({ ok: false, error: "Payload too large" }, 413);
    payload = JSON.parse(body);
  }
  catch { return json({ ok: false, error: "Invalid request" }, 400); }

  if (clean(payload.website, 200)) return json({ ok: true });
  if (!await rateLimit(request)) return json({ ok: false, error: "Too many requests" }, 429);

  const topic = clean(payload.topic, 30);
  const email = clean(payload.email, 254);
  const message = clean(payload.message, 2000);
  const locale = payload.locale === "zh" ? "zh" : "en";
  if (!TOPICS.has(topic) || message.length < 10) return json({ ok: false, error: "Please complete the required fields" }, 400);
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ ok: false, error: "Invalid email" }, 400);

  const recipient = clean(env.FEEDBACK_RECIPIENT, 254);
  if (!recipient) return json({ ok: false, error: "Feedback service is not configured" }, 503);

  let upstream;
  try {
    upstream = await fetch(`https://formsubmit.co/ajax/${encodeURIComponent(recipient)}`, {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        _subject: `[Polyemergence Feedback] ${TOPIC_LABELS[topic]}`,
        _template: "table",
        _captcha: "false",
        topic: TOPIC_LABELS[topic],
        message,
        reply_email: email || "Not provided",
        language: locale,
        page: clean(request.headers.get("Referer"), 500) || `https://${requestUrl.host}/`,
        submitted_at: new Date().toISOString()
      })
    });
  } catch {
    return json({ ok: false, error: "Delivery failed" }, 502);
  }

  let result = null;
  try { result = await upstream.json(); } catch {}
  if (!upstream.ok || result?.success === false) return json({ ok: false, error: "Delivery failed" }, 502);
  return json({ ok: true });
}

export function onRequestGet() {
  return json({ ok: false, error: "Method not allowed" }, 405);
}
