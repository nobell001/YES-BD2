/**
 * YES-BD2 update relay (Cloudflare Worker).
 *
 * Forwards ONLY what the YES-BD2 launcher and installers need from GitHub,
 * so players whose network can't reach github.com can still install and
 * update.  Everything else answers 403: this is not a general GitHub proxy.
 *
 *   https://<this-domain>/nobell001/YES-BD2-update.git/...   git fetch / clone (read only)
 *   https://<this-domain>/nobell001/YES-BD2/releases/download/<tag>/<file>
 *   https://<this-domain>/healthz                             "ok"
 */

const OWNER = "nobell001";
const GIT_REPOS = new Set(["YES-BD2-update", "YES-BD2"]);
const RELEASE_REPOS = new Set(["YES-BD2"]);

// /<owner>/<repo>[.git]/info/refs  or  /<owner>/<repo>[.git]/git-upload-pack
const GIT_RE = /^\/([^/]+)\/([^/]+?)(?:\.git)?\/(info\/refs|git-upload-pack)$/;
// /<owner>/<repo>/releases/download/<tag>/<file>
const RELEASE_RE = /^\/([^/]+)\/([^/]+)\/releases\/download\/([^/]+)\/([^/]+)$/;

function deny(status, text) {
  return new Response(text + "\n", {
    status,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
  });
}

function forwardHeaders(request) {
  const headers = new Headers();
  for (const name of ["accept", "content-type", "git-protocol", "range", "user-agent"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (!headers.has("user-agent")) headers.set("user-agent", "yes-bd2-relay");
  return headers;
}

async function relayGit(request, url, path) {
  const isRefs = path.endsWith("/info/refs");
  if (isRefs) {
    if (request.method !== "GET" && request.method !== "HEAD") return deny(405, "GET only");
    // Push (git-receive-pack) is never relayed.
    if (url.searchParams.get("service") !== "git-upload-pack") return deny(403, "read only");
  } else if (request.method !== "POST") {
    return deny(405, "POST only");
  }
  const target = "https://github.com" + path + url.search;
  const init = { method: request.method, headers: forwardHeaders(request), redirect: "follow" };
  // The fetch request is small (the list of wanted commits); buffering it
  // also lets GitHub see its length.
  if (request.method === "POST") init.body = await request.arrayBuffer();
  const reply = await fetch(target, init);
  const headers = new Headers(reply.headers);
  headers.delete("set-cookie");
  return new Response(reply.body, { status: reply.status, headers });
}

async function relayRelease(request, path) {
  if (request.method !== "GET" && request.method !== "HEAD") return deny(405, "GET only");
  // GitHub answers with a redirect to its file storage; follow it here so the
  // player never has to reach that host either.
  const reply = await fetch("https://github.com" + path, {
    method: request.method,
    headers: forwardHeaders(request),
    redirect: "follow",
  });
  const headers = new Headers();
  for (const name of ["content-type", "content-length", "content-range", "accept-ranges", "etag", "last-modified"]) {
    const value = reply.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(reply.body, { status: reply.status, headers });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;
    if (path === "/healthz") return deny(200, "ok");

    const git = path.match(GIT_RE);
    if (git && git[1] === OWNER && GIT_REPOS.has(git[2])) return relayGit(request, url, path);

    const release = path.match(RELEASE_RE);
    if (release && release[1] === OWNER && RELEASE_REPOS.has(release[2])) return relayRelease(request, path);

    return deny(403, "not relayed");
  },
};
