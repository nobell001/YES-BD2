/**
 * YES-BD2 匿名上传站 (Cloudflare Worker, Leo 2026-11-05).
 *
 * The tool's 「匿名上传完整记录」 button sends ONE record bundle (a zip, as
 * base64 text) here; the station files it in the private GitHub repo
 * REPORTS_REPO as reports/<YYYY-MM-DD>/<CODE>.zip and answers {"code": CODE}.
 * The player posts the code (or the summary picture, which shows it); the
 * author reads the bundle by its code.
 *
 *   POST https://<this-domain>/upload    body: base64 of the zip   -> {"code":"K7M2QX"}
 *   GET  https://<this-domain>/healthz   "ok"
 *
 * Secrets / vars (Worker → Settings → Variables and Secrets):
 *   REPORTS_TOKEN  (secret) fine-grained GitHub token, ONLY the reports repo,
 *                  permission Contents: Read and write.
 *   REPORTS_REPO   (text)   e.g. nobell001/yes-bd2-reports
 * Optional binding LIMITER (Rate limiting): a few uploads per minute per IP.
 *
 * The bundle is base64-encoded by the tool, so this Worker only checks and
 * forwards text: it stays inside the Free plan's CPU limit.
 */

const MAX_BASE64 = 6 * 1024 * 1024; // the tool sends at most 4 MB of zip
const ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"; // no 0/O, 1/I/L
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

function reply(status, body) {
  return new Response(JSON.stringify(body) + "\n", {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function newCode() {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join("");
}

async function store(env, code, content, agent) {
  const day = new Date().toISOString().slice(0, 10);
  const path = `reports/${day}/${code}.zip`;
  // Built by hand: the content is already base64 (checked above).
  const body =
    `{"message":${JSON.stringify(`report ${code} (${agent.slice(0, 40)})`)},` +
    `"content":"${content}"}`;
  return fetch(`https://api.github.com/repos/${env.REPORTS_REPO}/contents/${path}`, {
    method: "PUT",
    headers: {
      authorization: `Bearer ${env.REPORTS_TOKEN}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "yes-bd2-report-station",
      "x-github-api-version": "2022-11-28",
    },
    body,
  });
}

async function upload(request, env) {
  const agent = request.headers.get("user-agent") || "";
  if (!agent.startsWith("YES-BD2")) return reply(403, { error: "不是 YES-BD2 送来的" });
  if (env.LIMITER) {
    const ip = request.headers.get("cf-connecting-ip") || "?";
    const { success } = await env.LIMITER.limit({ key: ip });
    if (!success) return reply(429, { error: "上传太频繁，请过一分钟再试" });
  }
  const size = Number(request.headers.get("content-length") || 0);
  if (size > MAX_BASE64) return reply(413, { error: "记录太大" });
  const content = (await request.text()).trim();
  if (content.length > MAX_BASE64) return reply(413, { error: "记录太大" });
  // A zip starts with "PK\x03\x04", which is "UEsDB" in base64.
  if (!content.startsWith("UEsDB") || !BASE64.test(content)) {
    return reply(400, { error: "内容不对" });
  }
  for (let tries = 0; tries < 3; tries++) {
    const code = newCode();
    const answer = await store(env, code, content, agent);
    if (answer.ok) return reply(200, { code });
    if (answer.status !== 422) {
      // 422 = that code is taken today: draw another.
      return reply(502, { error: `存放失败 ${answer.status}` });
    }
  }
  return reply(502, { error: "存放失败" });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/healthz") return new Response("ok\n");
    if (url.pathname === "/upload" && request.method === "POST") return upload(request, env);
    return reply(404, { error: "not here" });
  },
};
