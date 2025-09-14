// FINAL worker.js
// Cloudflare Worker that extracts a direct dlink from a TeraBox/1024terabox share link.
// Replace COOKIE with a fresh logged-in cookie (must include PANWEB and ndus).
//
// Endpoints:
//  GET  /get?url=<share-url>   -> returns JSON { file_name, file_size, size_bytes, thumbnail, download_link, proxy_url, debug? }
//  GET  /proxy?url=<dlink>&file_name=<name> -> streams the file (supports Range)
//  OPTIONS -> handles CORS preflight
//
// Notes:
// - This tries the full sequence: fetch share page -> parse tokens -> /share/list -> /api/home/info -> /api/download
// - It also tries sensible fallbacks in order (different domains/endpoints and sign/timestamp sources).
// - Keep your COOKIE fresh. If endpoints return HTML instead of JSON, cookie/session is probably invalid.

const COOKIE = "<PUT-YOUR-FRESH-COOKIE-HERE>"; // e.g. "PANWEB=1; ndus=....; other=..."

const COMMON_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  "Connection": "keep-alive",
  "DNT": "1",
  "Cookie": COOKIE,
  "X-Requested-With": "XMLHttpRequest"
};

const DL_HEADERS = {
  "User-Agent": COMMON_HEADERS["User-Agent"],
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
  "Referer": "https://terabox.com/",
  "Cookie": COOKIE
};

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type,Range",
  "Access-Control-Expose-Headers": "Content-Length,Content-Range"
};

function getSize(sizeBytes) {
  const n = Number(sizeBytes) || 0;
  if (n >= 1024 * 1024 * 1024) return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(2)} KB`;
  return `${n} bytes`;
}

function safeJSONParse(text) {
  try {
    return { ok: true, json: JSON.parse(text) };
  } catch (e) {
    return { ok: false, err: e, snippet: text?.slice?.(0, 1000) || "" };
  }
}

function findBetween(str = "", start, end) {
  const s = str.indexOf(start);
  if (s === -1) return "";
  const e = str.indexOf(end, s + start.length);
  if (e === -1) return "";
  return str.slice(s + start.length, e);
}

async function fetchText(url, headers = COMMON_HEADERS) {
  const res = await fetch(url, { headers, redirect: "follow" });
  const text = await res.text();
  return { ok: res.ok, status: res.status, url: res.url, text };
}

async function fetchJson(url, headers = COMMON_HEADERS) {
  const res = await fetch(url, { headers, redirect: "follow" });
  const txt = await res.text();
  if (!txt) return { ok: false, reason: "empty_response", status: res.status, text: txt };
  if (txt.trim().startsWith("<")) return { ok: false, reason: "html_response", status: res.status, text: txt.slice(0, 1000) };
  const p = safeJSONParse(txt);
  if (!p.ok) return { ok: false, reason: "json_parse_error", status: res.status, text: txt.slice(0, 1000) };
  return { ok: true, json: p.json, status: res.status };
}

// Extract tokens (jsToken, logid, bdstoken) and possible embedded shareid/uk
function extractTokensFromHtml(html) {
  const result = {};
  // jsToken commonly appears in forms like fn%28%22HEX%22%29 or fn("HEX") in function wrapper
  const jsPct = (html.match(/fn%28%22([0-9A-Fa-f]+)%22%29/) || [])[1];
  const jsFn = (html.match(/fn\(\s*['"]([0-9A-Fa-f]+)['"]\s*\)/) || [])[1];
  const jsField = (html.match(/"jsToken"\s*[:=]\s*["']([^"']+)["']/) || [])[1];
  result.jsToken = jsPct || jsFn || jsField || "";

  result.logid = (html.match(/dp-logid=([0-9]+)/) || [])[1] || (html.match(/"dp-logid"\s*[:=]\s*["']([^"']+)["']/) || [])[1] || "";
  result.bdstoken = (html.match(/"bdstoken"\s*[:=]\s*["']([^"']+)["']/) || [])[1] || (html.match(/bdstoken":"([^"]+)"/) || [])[1] || "";

  // Try shareid/uk in inline JSON or window.__INITIAL_STATE__
  result.shareid = (html.match(/"shareid"\s*:\s*([0-9]+)/) || [])[1] || "";
  result.uk = (html.match(/"uk"\s*:\s*([0-9]+)/) || [])[1] || "";

  // try parse __INITIAL_STATE__ if present
  const stateMatch = html.match(/window\.__INITIAL_STATE__\s*=\s*(\{[\s\S]*?\});/);
  if ((!result.shareid || !result.uk) && stateMatch) {
    try {
      const st = JSON.parse(stateMatch[1]);
      if (!result.shareid) result.shareid = st?.shareInfo?.shareId || result.shareid;
      if (!result.uk) result.uk = st?.shareInfo?.uk || result.uk;
    } catch (e) {
      // ignore parse errors
    }
  }

  return result;
}

// Calls dm.terabox.app/share/list to get file list and optional claim info
async function callShareList(finalUrl, shorturl, jsToken, logid, bdstoken) {
  const params = new URLSearchParams({
    app_id: "250528",
    web: "1",
    channel: "dubox",
    clienttype: "0",
    jsToken: jsToken || "",
    "dp-logid": logid || "",
    page: "1",
    num: "50",
    by: "name",
    order: "asc",
    site_referer: finalUrl || "",
    shorturl: shorturl || "",
    root: "1,"
  });
  if (bdstoken) params.set("bdstoken", bdstoken);
  const url = `https://dm.terabox.app/share/list?${params.toString()}`;
  return await fetchJson(url, COMMON_HEADERS);
}

// Calls /api/home/info to get sign/timestamp/uk
async function callHomeInfo(jsToken, logid) {
  const params = new URLSearchParams({
    app_id: "250528",
    web: "1",
    channel: "dubox",
    clienttype: "0",
    jsToken: jsToken || "",
    "dp-logid": logid || ""
  });
  const url = `https://www.1024terabox.com/api/home/info?${params.toString()}`;
  return await fetchJson(url, COMMON_HEADERS);
}

// Calls /api/download on provided domain with given query params
async function callDownloadApi(domain, paramsObj) {
  const params = new URLSearchParams(paramsObj);
  const url = `${domain}/api/download?${params.toString()}`;
  return await fetchJson(url, COMMON_HEADERS);
}

// Try multiple download variations (including the "button" variant you captured)
async function attemptDownloadUnlock({ fs_id, jsToken, logid, bdstoken, shorturl, listData, homeData }) {
  const attempts = [];

  // helper to run and collect
  async function runAttempt(domain, paramsObj, note) {
    const res = await callDownloadApi(domain, paramsObj);
    attempts.push({ domain, params: paramsObj, result: res });
    if (res.ok && res.json && (res.json.dlink || (res.json.list && res.json.list[0] && res.json.list[0].dlink))) {
      // unify extraction
      let dlink = "";
      if (res.json.dlink && Array.isArray(res.json.dlink) && res.json.dlink[0]?.dlink) dlink = res.json.dlink[0].dlink;
      else if (res.json.list && Array.isArray(res.json.list) && res.json.list[0]?.dlink) dlink = res.json.list[0].dlink;
      else if (res.json.url) dlink = res.json.url;
      return { ok: true, dlink, raw: res.json, note };
    }
    return { ok: false, res };
  }

  // Build possible sign/timestamp sources in order of likely correctness
  const candidateSignTs = [];

  // If listData contains sign/timestamp
  if (listData) {
    if (listData.sign || listData.timestamp) candidateSignTs.push({ sign: listData.sign, timestamp: listData.timestamp });
    if (listData.data && (listData.data.sign || listData.data.timestamp)) candidateSignTs.push({ sign: listData.data.sign, timestamp: listData.data.timestamp });
  }

  // If homeData contains sign1, sign3, timestamp, uk
  if (homeData && homeData.data) {
    const hd = homeData.data;
    // direct timestamp if provided
    if (hd.timestamp) candidateSignTs.push({ sign: hd.sign1 || hd.sign3 || hd.sign || "", timestamp: hd.timestamp });
    // if sign3 is a short hex, try it too
    if (hd.sign3) candidateSignTs.push({ sign: hd.sign3, timestamp: hd.timestamp || "" });
    if (hd.sign1) candidateSignTs.push({ sign: hd.sign1, timestamp: hd.timestamp || "" });
  }

  // Add a fallback empty signature attempt (some deployments accept)
  candidateSignTs.push({ sign: "", timestamp: homeData?.data?.timestamp || Math.floor(Date.now() / 1000) });

  // Primary domain attempts (use the "button" pattern you captured)
  const domains = [
    "https://www.1024terabox.com",
    "https://www.terabox.app",
    "https://d.1024terabox.com",
    "https://d.terabox.com",
    "https://dm.terabox.app"
  ];

  for (const cand of candidateSignTs) {
    // build fidlist as JSON array string
    const fidlist = `[${fs_id}]`;
    for (const domain of domains) {
      const paramsObj = {
        app_id: "250528",
        web: "1",
        channel: "dubox",
        clienttype: "0",
        jsToken: jsToken || "",
        "dp-logid": logid || "",
        fidlist,
        type: "dlink",
        vip: "2",
        sign: cand.sign || "",
        timestamp: cand.timestamp || "",
        need_speed: "0",
        bdstoken: bdstoken || ""
      };
      // also include shorturl if we have it
      if (shorturl) paramsObj.shorturl = shorturl;
      const r = await runAttempt(domain, paramsObj, `download-button-mimic @ ${domain}`);
      if (r.ok) return { ok: true, dlink: r.dlink, source: r.note, raw: r.raw, attempts };
    }
  }

  // As additional fallback try legacy or alternate endpoints /share/download or /api/download with primaryid param
  for (const domain of domains) {
    const paramsObjAlt = {
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      primaryid: fs_id,
      jsToken: jsToken || "",
      "dp-logid": logid || "",
      bdstoken: bdstoken || ""
    };
    const r = await runAttempt(domain, paramsObjAlt, `primaryid attempt @ ${domain}`);
    if (r.ok) return { ok: true, dlink: r.dlink, source: r.note, raw: r.raw, attempts };
  }

  return { ok: false, attempts };
}

// Main orchestration: does full flow for a given share link
async function resolveShareToDlink(shareLink) {
  // Step 0: fetch share page
  const first = await fetchText(shareLink, COMMON_HEADERS);
  if (!first.ok) {
    return { ok: false, error: "initial_fetch_failed", status: first.status, snippet: first.text?.slice(0, 400) };
  }
  const finalUrl = first.url;
  let shorturl = null;
  try {
    shorturl = new URL(finalUrl).searchParams.get("surl") || null;
  } catch (e) {
    shorturl = null;
  }

  const tokens = extractTokensFromHtml(first.text);
  let { jsToken, logid, bdstoken, shareid, uk } = tokens;

  // if jsToken appears encoded like percent encoding, decode basic form
  if (jsToken && jsToken.includes("%")) {
    try {
      jsToken = decodeURIComponent(jsToken);
    } catch (e) {}
  }

  // Step 1: call share/list
  const listResp = await callShareList(finalUrl, shorturl, jsToken, logid, bdstoken);
  if (!listResp.ok) {
    return { ok: false, error: "share_list_failed", detail: listResp };
  }
  const listJson = listResp.json;
  const listFiles = listJson?.list || [];
  if (!listFiles.length) {
    return { ok: false, error: "no_files_in_share", listJson };
  }
  // pick the first file by default
  const f = listFiles[0];
  const fs_id = f?.fs_id || f?.primaryid || null;
  const server_filename = f?.server_filename || f?.server_filename || f?.filename || "download";
  const size = f?.size || f?.filesize || null;
  // list might include sign/timestamp too
  const listSign = listJson?.sign || f?.sign || null;
  const listTimestamp = listJson?.timestamp || f?.timestamp || null;

  // Step 1b: ensure shareid/uk if not found
  shareid = shareid || listJson?.shareid || null;
  uk = uk || listJson?.uk || null;

  // Step 2: call /api/home/info to obtain timestamps/signs/uk
  const homeResp = await callHomeInfo(jsToken, logid);
  let homeJson = null;
  if (homeResp.ok) {
    homeJson = homeResp.json;
    // if home provides uk or timestamp, use them
    uk = uk || homeJson?.data?.uk || uk;
  }

  // Step 3: attempt to get dlink by trying various download API shapes
  const unlock = await attemptDownloadUnlock({
    fs_id,
    jsToken,
    logid,
    bdstoken,
    shorturl,
    listData: listJson,
    homeData: homeJson
  });

  // Build response
  if (unlock.ok) {
    const dlink = unlock.dlink;
    return {
      ok: true,
      file_name: server_filename,
      file_size: getSize(size),
      size_bytes: Number(size) || null,
      thumbnail: f?.thumbs?.url3 || f?.thumbs?.url2 || f?.thumbs?.url1 || null,
      download_link: dlink,
      proxy_url: dlink ? `/proxy?url=${encodeURIComponent(dlink)}&file_name=${encodeURIComponent(server_filename)}` : "",
      raw: { listJson, homeJson, unlockRaw: unlock.raw, unlockSource: unlock.source }
    };
  } else {
    return { ok: false, error: "failed_to_obtain_dlink", debug: unlock.attempts || unlock, listJson, homeJson };
  }
}

// Proxy download streaming handler
async function proxyDownload(url, fileName, request) {
  try {
    const headers = new Headers(DL_HEADERS);
    const range = request.headers.get("Range");
    if (range) headers.set("Range", range);

    const resp = await fetch(url, { headers, redirect: "follow" });

    if (!resp.ok && resp.status !== 206) {
      return new Response(JSON.stringify({ error: `Upstream fetch failed: ${resp.status}` }), { status: 502, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
    }

    const outHeaders = new Headers();
    outHeaders.set("Content-Type", resp.headers.get("Content-Type") || "application/octet-stream");
    outHeaders.set("Content-Disposition", `inline; filename="${encodeURIComponent(fileName)}"`);
    outHeaders.set("Accept-Ranges", "bytes");
    if (resp.headers.has("Content-Range")) outHeaders.set("Content-Range", resp.headers.get("Content-Range"));
    if (resp.headers.has("Content-Length")) outHeaders.set("Content-Length", resp.headers.get("Content-Length"));
    // CORS
    for (const [k, v] of Object.entries(CORS_HEADERS)) outHeaders.set(k, v);

    return new Response(resp.body, { status: resp.status, headers: outHeaders });
  } catch (e) {
    return new Response(JSON.stringify({ error: `Proxy exception: ${String(e)}` }), { status: 500, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
  }
}

// Worker handler (routes)
export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    // GET /get?url=...
    if (request.method === "GET" && (url.pathname === "/get" || url.pathname === "/")) {
      const shareLink = url.searchParams.get("url");
      if (!shareLink) {
        return new Response(JSON.stringify({ error: "No url param provided. Use ?url=<share-link>" }), {
          status: 400, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }
      try {
        const res = await resolveShareToDlink(shareLink);
        if (res.ok) {
          return new Response(JSON.stringify({
            file_name: res.file_name,
            file_size: res.file_size,
            size_bytes: res.size_bytes,
            thumbnail: res.thumbnail,
            download_link: res.download_link,
            proxy_url: url.origin + (res.proxy_url || ""),
            raw: res.raw
          }), { status: 200, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
        } else {
          return new Response(JSON.stringify(res), { status: 502, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
        }
      } catch (e) {
        return new Response(JSON.stringify({ error: "Unhandled exception", message: String(e) }), { status: 500, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
      }
    }

    // GET /proxy?url=...&file_name=...
    if (request.method === "GET" && url.pathname === "/proxy") {
      const downloadUrl = url.searchParams.get("url");
      const fileName = url.searchParams.get("file_name") || "download";
      if (!downloadUrl) {
        return new Response(JSON.stringify({ error: "No url param for proxy." }), { status: 400, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
      }
      return proxyDownload(downloadUrl, fileName, request);
    }

    // POST / (optional) accept JSON body { link: "..." }
    if (request.method === "POST" && url.pathname === "/") {
      try {
        const body = await request.json().catch(() => ({}));
        const link = body.link || body.url;
        if (!link) {
          return new Response(JSON.stringify({ error: "No link in POST body." }), { status: 400, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
        }
        const res = await resolveShareToDlink(link);
        return new Response(JSON.stringify(res), { status: res.ok ? 200 : 502, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
      } catch (e) {
        return new Response(JSON.stringify({ error: "Invalid JSON body", message: String(e) }), { status: 400, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
      }
    }

    return new Response(JSON.stringify({ error: "Not found" }), { status: 404, headers: { "Content-Type": "application/json", ...CORS_HEADERS } });
  }
};
```0