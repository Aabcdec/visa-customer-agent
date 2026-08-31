/**
 * Cloudflare Worker：给纯静态 H5 做同源/可 CORS 的 API 代理
 *
 * 部署（约 2 分钟）：
 * 1. 打开 https://dash.cloudflare.com → Workers & Pages → Create Worker
 * 2. 粘贴本文件代码 → Deploy
 * 3. Settings → Variables → 添加密钥 TOKEN = 你的 Bearer（扣子部署 Token）
 * 4. 复制 Worker 地址，形如 https://visa-h5-proxy.xxx.workers.dev
 * 5. 改 h5/config.js：
 *      apiUrl: "https://visa-h5-proxy.xxx.workers.dev"
 *      apiToken 可留空（Worker 用环境变量 TOKEN）
 *
 * 本地预览也可用该 Worker 地址，无需 python。
 */

const UPSTREAM = "http://127.0.0.1:5000/run";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Max-Age": "86400",
};

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    if (request.method === "GET") {
      return json({ ok: true, upstream: UPSTREAM }, 200);
    }

    if (request.method !== "POST") {
      return json({ message: "Method Not Allowed" }, 405);
    }

    const auth =
      request.headers.get("Authorization") ||
      (env.TOKEN ? `Bearer ${env.TOKEN}` : "");

    if (!auth) {
      return json(
        { message: "缺少 Token：请在 Worker 密钥 TOKEN 中配置，或请求头带 Authorization" },
        401
      );
    }

    let bodyText = await request.text();
    if (!bodyText) {
      bodyText = "{}";
    }

    try {
      const upstream = await fetch(UPSTREAM, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          Authorization: auth,
        },
        body: bodyText,
      });

      const text = await upstream.text();
      return new Response(text, {
        status: upstream.status,
        headers: {
          ...CORS,
          "Content-Type":
            upstream.headers.get("Content-Type") || "application/json; charset=utf-8",
        },
      });
    } catch (err) {
      return json({ message: String(err && err.message ? err.message : err) }, 502);
    }
  },
};

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...CORS, "Content-Type": "application/json; charset=utf-8" },
  });
}
