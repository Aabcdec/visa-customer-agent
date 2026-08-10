(() => {
  const BAKED_VERSION = 3; // 升版本可强制丢弃本机旧设置
  const REMOTE_API = "https://5dq8j354gp.coze.site/run";
  const baked = window.VISA_H5_CONFIG || {};
  const STORAGE_KEY = "visa_h5_api_config_v1";

  const chat = document.getElementById("chat");
  const composer = document.getElementById("composer");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("sendBtn");
  const chips = document.getElementById("chips");
  const settingsBtn = document.getElementById("settingsBtn");
  const settings = document.getElementById("settings");
  const settingsForm = document.getElementById("settingsForm");
  const apiUrlInput = document.getElementById("apiUrl");
  const apiTokenInput = document.getElementById("apiToken");

  function loadConfig() {
    const base = {
      apiUrl: (baked.apiUrl || REMOTE_API).trim(),
      apiToken: (baked.apiToken || "").trim(),
      version: BAKED_VERSION,
    };
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return base;
      const saved = JSON.parse(raw);
      // 版本过期或指向 coze.site / 空地址 → 强制用 config.js
      if (
        saved.version !== BAKED_VERSION ||
        !saved.apiUrl ||
        /coze\.site/i.test(saved.apiUrl)
      ) {
        localStorage.removeItem(STORAGE_KEY);
        return base;
      }
      return {
        apiUrl: saved.apiUrl.trim(),
        apiToken: (saved.apiToken || base.apiToken).trim(),
        version: BAKED_VERSION,
      };
    } catch (_) {
      return base;
    }
  }

  function saveConfig(cfg) {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...cfg, version: BAKED_VERSION })
    );
  }

  let config = loadConfig();

  function appendMessage(role, text, meta) {
    const wrap = document.createElement("article");
    wrap.className = `msg ${role}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (role === "bot" && text === "__typing__") {
      bubble.innerHTML =
        '<span class="typing" aria-label="正在回复"><i></i><i></i><i></i></span>';
    } else {
      bubble.textContent = text;
    }
    wrap.appendChild(bubble);

    if (meta && Object.keys(meta).length) {
      const row = document.createElement("div");
      row.className = "meta";
      const items = [
        meta.intent && { label: `意图 ${meta.intent}`, cls: "" },
        meta.flow_path && {
          label: `路径 ${meta.flow_path}`,
          cls:
            meta.flow_path === "confirm"
              ? "confirm"
              : meta.flow_path === "handoff"
                ? "handoff"
                : "ok",
        },
        meta.risk_level && {
          label: `风险 ${meta.risk_level}`,
          cls:
            meta.risk_level === "high"
              ? "handoff"
              : meta.risk_level === "medium"
                ? "confirm"
                : "ok",
        },
        meta.need_handoff && { label: "转人工", cls: "handoff" },
      ].filter(Boolean);
      for (const item of items) {
        const tag = document.createElement("span");
        tag.className = `tag ${item.cls}`.trim();
        tag.textContent = item.label;
        row.appendChild(tag);
      }
      wrap.appendChild(row);
    }

    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  function extractReply(data) {
    if (!data || typeof data !== "object") {
      return { text: String(data ?? "空响应"), meta: {} };
    }
    const text =
      data.final_reply ||
      data.reply ||
      data.message ||
      data.output ||
      (typeof data.result === "string" ? data.result : null) ||
      JSON.stringify(data, null, 2);

    return {
      text,
      meta: {
        intent: data.intent,
        flow_path: data.flow_path,
        risk_level: data.risk_level,
        need_handoff: Boolean(data.need_handoff),
      },
    };
  }

  async function callAgent(userMessage) {
    const url = (config.apiUrl || "").trim();
    const token = (config.apiToken || "").trim();
    if (!url || url.includes("REPLACE_ME") || /coze\.site/i.test(url)) {
      throw new Error(
        "当前 apiUrl 无效或仍指向 coze.site。请改用可访问的代理地址（国内建议阿里云 FC，见 proxy-cn/）。"
      );
    }

    const headers = { "Content-Type": "application/json" };
    if (token && !token.includes("YOUR_TOKEN")) {
      headers.Authorization = `Bearer ${token}`;
    }

    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify({ user_message: userMessage }),
      });
    } catch (err) {
      const isWorkers = /workers\.dev/i.test(url);
      throw new Error(
        `Failed to fetch（请求未到达或被拦截）\n当前接口：${url}\n` +
          (isWorkers
            ? "国内常访问不了 *.workers.dev。请：①手机浏览器直接打开该 Worker 地址测通；②不通则改用阿里云函数代理（h5/proxy-cn/aliyun-fc.js）。"
            : "请检查网络、是否用 https 打开页面、静态站是否已上传最新 config.js。") +
          `\n原始错误：${err && err.message ? err.message : err}`
      );
    }

    const rawText = await res.text();
    let data;
    try {
      data = rawText ? JSON.parse(rawText) : {};
    } catch {
      throw new Error(
        `服务返回非 JSON（${res.status}）：${rawText.slice(0, 200)}`
      );
    }

    if (!res.ok) {
      const detail = data.detail || data.message || rawText.slice(0, 240);
      throw new Error(`请求失败 ${res.status}：${detail}`);
    }
    return extractReply(data);
  }

  let busy = false;

  async function send(text) {
    const content = (text || "").trim();
    if (!content || busy) return;
    busy = true;
    sendBtn.disabled = true;
    appendMessage("user", content);
    input.value = "";
    autosize();
    const typing = appendMessage("bot", "__typing__");

    try {
      const { text: reply, meta } = await callAgent(content);
      typing.remove();
      appendMessage("bot", reply, meta);
    } catch (err) {
      typing.remove();
      appendMessage("system", String(err.message || err));
    } finally {
      busy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  }

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    send(input.value);
  });

  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input.value);
    }
  });

  chips.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-q]");
    if (!btn) return;
    send(btn.dataset.q);
  });

  settingsBtn.addEventListener("click", () => {
    apiUrlInput.value = config.apiUrl || "";
    apiTokenInput.value = config.apiToken || "";
    settings.showModal();
  });

  settingsForm.addEventListener("submit", (e) => {
    const submitter = e.submitter;
    if (submitter && submitter.value === "save") {
      config = {
        apiUrl: apiUrlInput.value.trim(),
        apiToken: apiTokenInput.value.trim(),
        version: BAKED_VERSION,
      };
      saveConfig(config);
      appendMessage("system", `已保存。当前接口：${config.apiUrl}`);
    }
  });

  appendMessage(
    "system",
    `你好，我是签证客服助手。\n当前接口：${config.apiUrl}\n` +
      "先用手机浏览器打开上面这个地址：能看到 ok 再回来提问；若打不开，说明代理在国内不可达，需换阿里云 FC（见 proxy-cn）。"
  );
})();
