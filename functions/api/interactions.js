const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer"
};

const ARTICLE_ID = /^[0-9a-f]{8}-[0-9a-f-]{27,36}$/i;
const MAX_ARTICLES = 50;
const MAX_COMMENT_LENGTH = 500;

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: JSON_HEADERS });
}

function clean(value, max = MAX_COMMENT_LENGTH) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
    .trim()
    .slice(0, max);
}

function validArticleId(value) {
  return ARTICLE_ID.test(String(value || ""));
}

async function sha256(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function requestIp(request) {
  return request.headers.get("CF-Connecting-IP") || "unknown";
}

function ipSuffix(ip) {
  if (ip === "unknown") return "---";
  if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(ip)) return ip.split(".").pop().padStart(3, "0");
  const compact = ip.replace(/[^0-9a-f]/gi, "").toUpperCase();
  return compact.slice(-3).padStart(3, "0");
}

function requestIdentity(request) {
  const cf = request.cf || {};
  return {
    alias: "poly",
    region: clean(cf.region || "", 80),
    region_code: clean(cf.regionCode || "", 12),
    country: clean(cf.country || request.headers.get("CF-IPCountry") || "", 12).toUpperCase(),
    ip_suffix: ipSuffix(requestIp(request))
  };
}

async function visitorHash(request, env) {
  const salt = clean(env.INTERACTIONS_HASH_SALT, 256);
  if (!salt) throw new Error("Interaction identity salt is not configured");
  return sha256(`${salt}:${requestIp(request)}:polyemergence-interactions`);
}

let schemaReady;

async function ensureSchema(db) {
  if (!schemaReady) schemaReady = db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS article_likes (
      article_id TEXT NOT NULL,
      visitor_hash TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY (article_id, visitor_hash)
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS article_comments (
      id TEXT PRIMARY KEY,
      article_id TEXT NOT NULL,
      visitor_hash TEXT NOT NULL,
      body TEXT NOT NULL,
      alias TEXT NOT NULL DEFAULT 'poly',
      region TEXT NOT NULL DEFAULT '',
      region_code TEXT NOT NULL DEFAULT '',
      country TEXT NOT NULL DEFAULT '',
      ip_suffix TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'visible',
      created_at TEXT NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_comments_article_created ON article_comments(article_id, created_at DESC)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS interaction_rate_limits (
      bucket TEXT PRIMARY KEY,
      count INTEGER NOT NULL,
      expires_at TEXT NOT NULL
    )`)
  ]).catch(error => {
    schemaReady = null;
    throw error;
  });
  await schemaReady;
}

function database(env) {
  if (!env.INTERACTIONS) throw new Error("Interaction database is not configured");
  return env.INTERACTIONS;
}

async function rateLimit(db, visitor, action, limit) {
  const hour = new Date().toISOString().slice(0, 13);
  const bucket = `${visitor}:${action}:${hour}`;
  const expires = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();
  const result = await db.prepare(`INSERT INTO interaction_rate_limits (bucket, count, expires_at)
    VALUES (?, 1, ?)
    ON CONFLICT(bucket) DO UPDATE SET count = count + 1
    RETURNING count`).bind(bucket, expires).first();
  if (Math.random() < 0.02) {
    await db.prepare("DELETE FROM interaction_rate_limits WHERE expires_at < ?").bind(new Date().toISOString()).run();
  }
  return Number(result?.count || 1) <= limit;
}

function sameOrigin(request) {
  const origin = request.headers.get("Origin");
  if (!origin) return true;
  try { return new URL(origin).host === new URL(request.url).host; }
  catch { return false; }
}

function publicComment(row) {
  return {
    id: row.id,
    article_id: row.article_id,
    body: row.body,
    identity: {
      alias: "poly",
      region: row.region || "",
      region_code: row.region_code || "",
      country: row.country || "",
      ip_suffix: row.ip_suffix || "---"
    },
    created_at: row.created_at
  };
}

async function summary(request, env, url) {
  const ids = [...new Set((url.searchParams.get("article_ids") || "").split(",").filter(validArticleId))].slice(0, MAX_ARTICLES);
  if (!ids.length) return json({ ok: true, items: {}, viewer: requestIdentity(request) });

  const db = database(env);
  await ensureSchema(db);
  const visitor = await visitorHash(request, env);
  const placeholders = ids.map(() => "?").join(",");
  const [likes, comments, mine] = await db.batch([
    db.prepare(`SELECT article_id, COUNT(*) AS count FROM article_likes WHERE article_id IN (${placeholders}) GROUP BY article_id`).bind(...ids),
    db.prepare(`SELECT article_id, COUNT(*) AS count FROM article_comments WHERE status = 'visible' AND article_id IN (${placeholders}) GROUP BY article_id`).bind(...ids),
    db.prepare(`SELECT article_id FROM article_likes WHERE visitor_hash = ? AND article_id IN (${placeholders})`).bind(visitor, ...ids)
  ]);

  const items = Object.fromEntries(ids.map(id => [id, { likes: 0, comments: 0, liked: false }]));
  for (const row of likes.results || []) items[row.article_id].likes = Number(row.count || 0);
  for (const row of comments.results || []) items[row.article_id].comments = Number(row.count || 0);
  for (const row of mine.results || []) items[row.article_id].liked = true;
  return json({ ok: true, items, viewer: requestIdentity(request) });
}

async function comments(request, env, url) {
  const articleId = url.searchParams.get("article_id") || "";
  if (!validArticleId(articleId)) return json({ ok: false, error: "Invalid article" }, 400);
  const db = database(env);
  await ensureSchema(db);
  const rows = await db.prepare(`SELECT id, article_id, body, region, region_code, country, ip_suffix, created_at
    FROM article_comments WHERE article_id = ? AND status = 'visible'
    ORDER BY created_at DESC LIMIT 30`).bind(articleId).all();
  return json({ ok: true, comments: (rows.results || []).map(publicComment), viewer: requestIdentity(request) });
}

export async function onRequestGet({ request, env }) {
  try {
    const url = new URL(request.url);
    return url.searchParams.get("view") === "comments" ? comments(request, env, url) : summary(request, env, url);
  } catch (error) {
    console.error("Interaction GET failed", error?.message || error);
    return json({ ok: false, error: "Interactions are temporarily unavailable" }, 503);
  }
}

export async function onRequestPost({ request, env }) {
  if (!sameOrigin(request)) return json({ ok: false, error: "Forbidden" }, 403);
  if (Number(request.headers.get("Content-Length") || 0) > 3000) return json({ ok: false, error: "Payload too large" }, 413);

  let payload;
  try {
    const raw = await request.text();
    if (raw.length > 3000) return json({ ok: false, error: "Payload too large" }, 413);
    payload = JSON.parse(raw);
  } catch {
    return json({ ok: false, error: "Invalid request" }, 400);
  }

  const articleId = clean(payload.article_id, 64);
  const action = clean(payload.action, 20);
  if (!validArticleId(articleId)) return json({ ok: false, error: "Invalid article" }, 400);

  try {
    const db = database(env);
    await ensureSchema(db);
    const visitor = await visitorHash(request, env);

    if (action === "like") {
      if (!await rateLimit(db, visitor, "like", 60)) return json({ ok: false, error: "Too many requests" }, 429);
      const liked = payload.liked === true;
      if (liked) {
        await db.prepare("INSERT OR IGNORE INTO article_likes (article_id, visitor_hash, created_at) VALUES (?, ?, ?)")
          .bind(articleId, visitor, new Date().toISOString()).run();
      } else {
        await db.prepare("DELETE FROM article_likes WHERE article_id = ? AND visitor_hash = ?").bind(articleId, visitor).run();
      }
      const row = await db.prepare("SELECT COUNT(*) AS count FROM article_likes WHERE article_id = ?").bind(articleId).first();
      return json({ ok: true, liked, likes: Number(row?.count || 0) });
    }

    if (action === "comment") {
      if (clean(payload.website, 200)) return json({ ok: true });
      if (!await rateLimit(db, visitor, "comment", 8)) return json({ ok: false, error: "Too many comments" }, 429);
      const body = clean(payload.body);
      if (body.length < 2) return json({ ok: false, error: "Comment is too short" }, 400);
      const identity = requestIdentity(request);
      const row = {
        id: crypto.randomUUID(), article_id: articleId, body,
        region: identity.region, region_code: identity.region_code,
        country: identity.country, ip_suffix: identity.ip_suffix,
        created_at: new Date().toISOString()
      };
      await db.prepare(`INSERT INTO article_comments
        (id, article_id, visitor_hash, body, alias, region, region_code, country, ip_suffix, status, created_at)
        VALUES (?, ?, ?, ?, 'poly', ?, ?, ?, ?, 'visible', ?)`)
        .bind(row.id, articleId, visitor, row.body, row.region, row.region_code, row.country, row.ip_suffix, row.created_at).run();
      const count = await db.prepare("SELECT COUNT(*) AS count FROM article_comments WHERE article_id = ? AND status = 'visible'").bind(articleId).first();
      return json({ ok: true, comment: publicComment(row), comments: Number(count?.count || 0) }, 201);
    }

    return json({ ok: false, error: "Unsupported action" }, 400);
  } catch (error) {
    console.error("Interaction POST failed", error?.message || error);
    return json({ ok: false, error: "Interactions are temporarily unavailable" }, 503);
  }
}

export function onRequestOptions() {
  return new Response(null, { status: 204, headers: JSON_HEADERS });
}
