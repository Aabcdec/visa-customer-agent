# Cloudflare Worker 代理（解决 H5 CORS）

网页「Quick Edit / Upload」会报：
`Please use wrangler deploy instead` —— 必须用命令行部署。

## 一次性步骤

在 PowerShell 中：

```powershell
cd f:\project_20260810_102613\h5\worker
npm install
npx wrangler login
```

浏览器登录 Cloudflare 后：

```powershell
npx wrangler secret put TOKEN
```

粘贴扣子部署页的 Bearer（不要带 `Bearer ` 前缀，只贴 token 本身）。

```powershell
npm run deploy
```

成功后终端会打印类似：

`https://visa-h5-proxy.<你的子域>.workers.dev`

把该地址写入 `h5/config.js`：

```js
window.VISA_H5_CONFIG = {
  apiUrl: "https://visa-h5-proxy.xxx.workers.dev",
  apiToken: "",
};
```

再重新上传静态 H5。

## 说明

- Node 建议 ≥ 18；本机若是 16，已锁定 wrangler@3。
- 不要再用 Dashboard 上传 JS 压缩包。
