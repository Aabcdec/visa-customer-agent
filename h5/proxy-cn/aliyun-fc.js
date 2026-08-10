/**
 * 阿里云函数计算 FC3 — HTTP 函数（Node.js 18/20）
 * 用作签证 H5 的国内 CORS 代理 → 扣子 /run
 *
 * 【控制台部署】
 * 1. 打开 https://fcnext.console.aliyun.com
 * 2. 创建应用 / 函数 → 选择「HTTP 函数」→ 运行环境 Node.js 18 或 20
 * 3. 将本文件内容粘贴为入口代码（handler 选 handler，或按控制台要求改名）
 * 4. 环境变量增加：
 *      TOKEN = 扣子部署页的 Bearer（不要加 Bearer 前缀）
 *      UPSTREAM = https://5dq8j354gp.coze.site/run   （可选，已有默认）
 * 5. 触发器：HTTP，公网访问，HTTPS
 * 6. 复制触发器地址，例如：
 *      https://xxx.cn-hangzhou.fcapp.run
 * 7. 改 h5/config.js：
 *      apiUrl: "https://xxx.cn-hangzhou.fcapp.run"
 *      apiToken: ""
 * 8. 手机浏览器先打开该地址，应看到 {"ok":true,...}，再打开 H5
 */

const UPSTREAM =
  process.env.UPSTREAM || "https://5dq8j354gp.coze.site/run";

function cors() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
    "Content-Type": "application/json; charset=utf-8",
  };
}

function getMethod(event) {
  return (
    event?.requestContext?.http?.method ||
    event?.httpMethod ||
    event?.method ||
    "GET"
  );
}

function getHeader(event, name) {
  const headers = event?.headers || {};
  const lower = name.toLowerCase();
  for (const [k, v] of Object.entries(headers)) {
    if (k.toLowerCase() === lower) return v;
  }
  return "";
}

function readBody(event) {
  let body = event?.body ?? "{}";
  if (event?.isBase64Encoded) {
    body = Buffer.from(body, "base64").toString("utf8");
  }
  if (typeof body !== "string") body = JSON.stringify(body);
  return body || "{}";
}

exports.handler = async (event, context) => {
  const method = String(getMethod(event)).toUpperCase();

  if (method === "OPTIONS") {
    return { statusCode: 204, headers: cors(), body: "" };
  }

  if (method === "GET") {
    return {
      statusCode: 200,
      headers: cors(),
      body: JSON.stringify({
        ok: true,
        upstream: UPSTREAM,
        tip: "POST JSON {user_message} 即可转发到扣子",
      }),
    };
  }

  if (method !== "POST") {
    return {
      statusCode: 405,
      headers: cors(),
      body: JSON.stringify({ message: "Method Not Allowed" }),
    };
  }

  const auth =
    getHeader(event, "authorization") ||
    (process.env.TOKEN ? `Bearer ${process.env.TOKEN}` : "");

  if (!auth) {
    return {
      statusCode: 401,
      headers: cors(),
      body: JSON.stringify({
        message: "请在函数环境变量配置 TOKEN（扣子 Bearer，不加前缀）",
      }),
    };
  }

  try {
    const resp = await fetch(UPSTREAM, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Authorization: auth,
      },
      body: readBody(event),
    });
    const text = await resp.text();
    return {
      statusCode: resp.status,
      headers: cors(),
      body: text,
    };
  } catch (err) {
    return {
      statusCode: 502,
      headers: cors(),
      body: JSON.stringify({
        message: String(err && err.message ? err.message : err),
      }),
    };
  }
};
