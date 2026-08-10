/**
 * 签证客服 H5 的 CORS 代理 → 扣子 /run
 * 部署: cd worker && npm i && npx wrangler secret put TOKEN && npm run deploy
 */
const UPSTREAM = "https://5dq8j354gp.coze.site/run";

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
        {
          message:
            "缺少 Token：请执行 npx wrangler secret put TOKEN，或在请求头带 Authorization",
        },
        401
      );
    }

    let bodyText = await request.text();
    if (!bodyText) bodyText = "{}";

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
            upstream.headers.get("Content-Type") ||
            "application/json; charset=utf-8",
        },
      });
    } catch (err) {
      return json(
        { message: String(err && err.message ? err.message : err) },
        502
      );
    }
  },
};

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      ...CORS,
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}
