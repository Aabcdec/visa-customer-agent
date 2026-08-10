# 国内访问方案（workers.dev 手机打不开时用这个）

结论：Cloudflare `*.workers.dev` 在国内经常完全打不开，H5 必然 Failed to fetch。  
需要换成 **国内可打开的 HTTPS 中转**，推荐阿里云函数计算（有免费额度）。

## 阿里云 FC 部署（约 10 分钟）

1. 登录 https://fcnext.console.aliyun.com （选离你近的地域，如杭州/上海）
2. **创建函数** → 类型选 **HTTP 函数**
3. 运行环境：**Node.js 18** 或 **20**
4. 代码：打开 [`aliyun-fc.js`](./aliyun-fc.js)，全文粘贴到在线编辑器  
   - 入口/handler 填：`handler`（若控制台要求 `index.handler`，文件名用 `index.js` 且导出 `handler`）
5. **环境变量**：
   - `TOKEN` = 扣子部署页给你的 Token（**不要**加 `Bearer `）
   - 可选 `UPSTREAM` = `https://5dq8j354gp.coze.site/run`
6. 触发器：HTTP、允许公网、HTTPS
7. 部署后复制触发器 URL（类似 `https://xxxxx.cn-hangzhou.fcapp.run`）
8. **手机浏览器先打开这个 URL**  
   - 看到 `{"ok":true,...}` 才算成功
9. 改 [`../config.js`](../config.js)：

```js
window.VISA_H5_CONFIG = {
  apiUrl: "https://你的触发器地址",
  apiToken: "",
};
```

10. 重新上传整个 `h5` 静态目录，强刷页面再提问

## 如果你有任意一台国内云主机

也可在服务器上跑 Nginx 反代到 `coze.site`，并加 CORS 头；H5 的 `apiUrl` 指向你的域名即可。比 FC 更稳，但需要机器。

## 不要再做的事

- 不要再把 `apiUrl` 设成 `*.workers.dev`（手机都打不开）
- 不要直连 `coze.site`（浏览器 CORS）
