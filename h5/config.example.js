/* ============================================================
 * H5 前端配置中心（复制为 config.js 后填写，再上传静态托管）
 *
 * 部署流程：
 * 1. 本地调试：保持默认 apiUrl = http://127.0.0.1:5000/run，
 *    后端执行 `bash scripts/run_local_deepseek.sh`（或 http_run.sh）
 * 2. 上线替换：只需把 apiUrl 改成你部署后的后端地址，例如：
 *      - 云服务器:    https://your-domain.com/run
 *      - Cloudflare:  https://your-worker.workers.dev/run
 *      - 阿里云FC:    https://your-fc-endpoint/run
 *    注意：后端需开启 CORS（main.py 已默认开启），否则浏览器会拦截跨域请求。
 * 3. 若后端要求鉴权，在 apiToken 填写 Bearer Token（无鉴权则留空）
 * ============================================================ */
window.VISA_H5_CONFIG = {
  apiUrl: "http://127.0.0.1:5000/run",
  apiToken: "",
};
