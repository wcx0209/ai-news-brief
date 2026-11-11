import {
  clampInt, filterArticles, findArticle, language, loadArticles,
  METHODOLOGY, publicArticle, searchArticles,
} from "./_lib/public-data.js";

const SERVER = { name: "polyemergence", title: "Polyemergence Emerging Intelligence", version: "1.1.0" };
const PROTOCOL_VERSIONS = ["2026-07-28", "2025-11-25"];
const HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept, MCP-Protocol-Version, MCP-Session-Id",
  "Access-Control-Expose-Headers": "MCP-Protocol-Version",
  "Cache-Control": "no-store",
  "Content-Type": "application/json; charset=utf-8",
  "MCP-Protocol-Version": PROTOCOL_VERSIONS[0],
  "X-Content-Type-Options": "nosniff",
};

const TOOLS = [
  {
    name: "search",
    title: "Search Polyemergence",
    description: "Search Polyemergence AI, biotech, programmable-life news and permanent archives. Returns canonical, citation-ready article URLs.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Keywords, company, model, person, topic, or event to search for." },
        language: { type: "string", enum: ["en", "zh"], default: "en" },
        limit: { type: "integer", minimum: 1, maximum: 20, default: 10 },
      },
      required: ["query"], additionalProperties: false,
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  {
    name: "fetch",
    title: "Fetch a Polyemergence article",
    description: "Retrieve one article summary, methodology scores, source metadata, and canonical URL by Polyemergence article ID.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", description: "Article ID returned by search or get_daily_brief." },
        language: { type: "string", enum: ["en", "zh"], default: "en" },
      },
      required: ["id"], additionalProperties: false,
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  {
    name: "get_daily_brief",
    title: "Get the latest Polyemergence brief",
    description: "Get the latest AI and programmable-life intelligence ranked by importance, optionally filtered by a registered category.",
    inputSchema: {
      type: "object",
      properties: {
        language: { type: "string", enum: ["en", "zh"], default: "en" },
        category: { type: "string", description: "A category slug from the public editorial-domain registry, such as models or biotech." },
        hours: { type: "integer", minimum: 1, maximum: 168, default: 48 },
        limit: { type: "integer", minimum: 1, maximum: 50, default: 20 },
      },
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  {
    name: "get_methodology",
    title: "Get the Polyemergence methodology",
    description: "Explain how Polyemergence ranks news and disclose its editorial process, publisher, and conflicts.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
];

function response(value, status = 200) {
  return new Response(value === null ? null : JSON.stringify(value), { status, headers: HEADERS });
}

function rpcResult(id, result) { return response({ jsonrpc: "2.0", id, result }); }
function rpcError(id, code, message, data) {
  return response({ jsonrpc: "2.0", id: id ?? null, error: { code, message, ...(data ? { data } : {}) } });
}
function toolResult(structuredContent, isError = false) {
  return {
    content: [{ type: "text", text: JSON.stringify(structuredContent) }],
    structuredContent,
    ...(isError ? { isError: true } : {}),
  };
}

async function callTool(name, args, env, request) {
  if (name === "get_methodology") return toolResult(METHODOLOGY);
  const payload = await loadArticles(env, request);
  const lang = language(args.language);
  if (name === "search") {
    const query = String(args.query || "").trim();
    if (!query) return toolResult({ error: "query is required" }, true);
    const items = searchArticles(payload, query, lang, clampInt(args.limit, 10, 1, 20));
    const results = items.map((item) => ({
      id: item.id, title: item.title, url: item.canonical_url,
      text: item.summary,
      metadata: { source: item.source, category: item.category, importance: item.importance, published_at: item.published_at },
    }));
    return toolResult({ results });
  }
  if (name === "fetch") {
    const article = findArticle(payload, args.id);
    if (!article) return toolResult({ error: "Article not found", id: String(args.id || "") }, true);
    const item = publicArticle(article, lang, true);
    return toolResult({
      id: item.id, title: item.title, text: item.full_summary, url: item.canonical_url,
      metadata: {
        summary: item.summary, source: item.source, source_url: item.source_url,
        category: item.category, importance: item.importance, scores: item.scores,
        published_at: item.published_at, source_published_at: item.source_published_at,
        tags: item.tags, language: item.language,
      },
    });
  }
  if (name === "get_daily_brief") {
    const params = new URLSearchParams({
      lang,
      hours: String(clampInt(args.hours, 48, 1, 168)),
      limit: String(clampInt(args.limit, 20, 1, 50)),
    });
    if (args.category) params.set("category", args.category);
    const result = filterArticles(payload, params);
    return toolResult({ generated_at: payload.generated_at, window_hours: result.hours, count: result.items.length, items: result.items });
  }
  return null;
}

export async function onRequestOptions() { return response(null, 204); }

export async function onRequestGet() {
  return response({
    name: SERVER.name,
    title: SERVER.title,
    transport: "Streamable HTTP (JSON response mode)",
    endpoint: "https://polyemergence.com/mcp",
    authentication: "none",
    documentation: "https://polyemergence.com/developers/",
    supported_protocol_versions: PROTOCOL_VERSIONS,
  });
}

export async function onRequestPost({ env, request }) {
  const length = Number(request.headers.get("content-length") || 0);
  if (length > 65536) return rpcError(null, -32600, "Request body is too large");
  let message;
  try { message = await request.json(); } catch { return rpcError(null, -32700, "Parse error"); }
  if (!message || message.jsonrpc !== "2.0" || typeof message.method !== "string") {
    return rpcError(message?.id, -32600, "Invalid Request");
  }
  const { id, method, params = {} } = message;
  if (method.startsWith("notifications/")) return response(null, 202);
  if (method === "ping") return rpcResult(id, {});
  if (method === "server/discover") {
    return rpcResult(id, { supportedVersions: PROTOCOL_VERSIONS, serverInfo: SERVER, capabilities: { tools: { listChanged: false } } });
  }
  if (method === "initialize") {
    const requested = params.protocolVersion;
    const protocolVersion = PROTOCOL_VERSIONS.includes(requested) ? requested : PROTOCOL_VERSIONS[0];
    return rpcResult(id, {
      protocolVersion, capabilities: { tools: { listChanged: false } }, serverInfo: SERVER,
      instructions: "Use search for discovery, fetch for a citation-ready article, and get_daily_brief for the latest ranked emerging-technology intelligence. Preserve canonical URLs when citing Polyemergence.",
    });
  }
  if (method === "tools/list") return rpcResult(id, { tools: TOOLS });
  if (method === "tools/call") {
    const name = params.name;
    const tool = TOOLS.find((candidate) => candidate.name === name);
    if (!tool) return rpcError(id, -32602, `Unknown tool: ${String(name || "")}`);
    try {
      const result = await callTool(name, params.arguments || {}, env, request);
      return rpcResult(id, result);
    } catch {
      return rpcResult(id, toolResult({ error: "Polyemergence data is temporarily unavailable" }, true));
    }
  }
  return rpcError(id, -32601, "Method not found");
}
