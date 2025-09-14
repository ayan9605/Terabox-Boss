// worker.js — Two-step Claim Ticket flow for TeraBox
// Replace COOKIE with a fresh logged-in cookie string that includes PANWEB and ndus.

const COOKIE = "PANWEB=1; ndus=...; <other_cookie_kv_pairs>"; // <-- REPLACE

const DISGUISE_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  "Connection": "keep-alive",
  "DNT": "1",
  "Referer": "https://terabox.com/",
  "Cookie": COOKIE,
  "X-Requested-With": "XMLHttpRequest"
};

const DL_HEADERS = {
  "User-Agent": DISGUISE_HEADERS["User-Agent"],
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
  "Referer": "https://terabox.com/",
  "Cookie": COOKIE,
};

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type,Range",
  "Access-Control-Expose-Headers": "Content-Length,Content-Range"
};

function safeJSONParse(text) {
  try { return { ok: true, json: JSON.parse(text) }; }
  catch (e) { return { ok: false, error: e, snippet: text.slice(0, 1000) }; }
}

function decodeJsTokenMaybe(raw) {
  // Common forms seen:
  // 1) percent-encoded form: fn%28%224F26...%22%29
  // 2) function wrapper string: function fn(a){...};fn("4F26...")
  if (!raw) return null;
  // Try percent-encoded pattern first
  const pct = raw.match(/fn%28%22([0-9A-Fa-f]+)%22%29/);
  if (pct) return decodeURIComponent(pct[1]);
  // Try plain function wrapper with quoted token
  const m1 = raw.match(/fn\(\s*["']([0-9A-Fa-f]+)["']\s*\)/);
  if (m1) return m1[1];
  // Try generic "jsToken":"TOKEN" appearances
  const m2 = raw.match(/"jsToken"\s*[:=]\s*["']([^"']+)["']/);
  if (m2) return m2[1];
  return raw;
}

async function fetchTextWithHeaders(url, headers = DISGUISE_HEADERS) {
  const res = await fetch(url, { headers, redirect: "follow" });
  const text = await res.text();
  return { ok: res.ok, status: res.status, url: res.url, text };
}

async function getShareList(finalUrl, shorturl, jsToken, logid, bdstoken) {
  // Build params as per Step 1
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
    site_referer: finalUrl,
    shorturl: shorturl || "",
    root: "1,"
  });
  // Add bdstoken as query if present (some variants require it)
  if (bdstoken) params.set("bdstoken", bdstoken);

  const url = `https://dm.terabox.app/share/list?${params.toString()}`;
  const resp = await fetch(url, { headers: DISGUISE_HEADERS, redirect: "follow" });
  const txt = await resp.text();
  const parsed = safeJSONParse(txt);
  if (!parsed.ok) {
    return { ok: false, reason: "share/list returned non-json", status: resp.status, snippet: txt.slice(0, 800) };
  }
  return { ok: true, json: parsed.json, status: resp.status };
}

async function getDownloadFromApi(downloadParams) {
  const url = `https://www.terabox.app/api/download?${downloadParams.toString()}`;
  const res = await fetch(url, { headers: DISGUISE_HEADERS, redirect: "follow" });
  const text = await res.text();
  const p = safeJSONParse(text);
  if (!p.ok) {
    return { ok: false, reason: "api/download returned non-json", status: res.status, snippet: text.slice(0, 800) };
  }
  return { ok: true, json: p.json, status: res.status };
}

function extractTokensFromHtml(text) {
  // try multiple strategies to get tokens
  // 1) percent-encoded jsToken pattern
  const jsTokenPct = (text.match(/fn%28%22([0-9A-Fa-f]+)%22%29/) || [])[1];
  // 2) function form
  const jsTokenFn = (text.match(/fn\(\s*["']([0-9A-Fa-f]+)["']\s*\)/) || [])[1];
  // 3) generic jsToken field
  const jsTokenField = (text.match(/"jsToken"\s*[:=]\s*["']([^"']+)["']/) || [])[1];

  const jsTokenRaw = jsTokenPct || jsTokenFn || jsTokenField || null;
  const jsToken = decodeJsTokenMaybe(jsTokenRaw);

  const logid = (text.match(/dp-logid=([0-9]+)/) || [])[1] || (text.match(/"dp-logid"\s*[:=]\s*["']([^"']+)["']/) || [])[1] || null;
  const bdstoken = (text.match(/"bdstoken"\s*[:=]\s*["']([^"']+)["']/) || [])[1] || (text.match(/bdstoken":"([^"]+)"/) || [])[1] || null;

  // Try shareid and uk from inline JSON or window.__INITIAL_STATE__
  let shareid = (text.match(/"shareid":\s*([0-9]+)/) || [])[1] || null;
  let uk = (text.match(/"uk":\s*([0-9]+)/) || [])[1] || null;
  if ((!shareid || !uk)) {
    const stateMatch = text.match(/window\.__INITIAL_STATE__\s*=\s*(\{[\s\S]*?\});/);
    if (stateMatch) {
      try {
        const j = JSON.parse(stateMatch[1]);
        if (!shareid && j?.shareInfo?.shareId) shareid = j.shareInfo.shareId;
        if (!uk && j?.shareInfo?.uk) uk = j.shareInfo.uk;
      } catch (e) {
        // ignore
      }
    }
  }

  return { jsToken, logid, bdstoken, shareid, uk };
}

async function tryInitApiForShare(surl) {
  // fallback to share/init which sometimes returns shareid/uk in JSON
  const url = `https://www.terabox.com/share/init?surl=${encodeURIComponent(surl)}`;
  const res = await fetch(url, { headers: { ...DISGUISE_HEADERS, Accept: "application/json, text/plain, */*" } , redirect: "follow" });
  const txt = await res.text();
  const parsed = safeJSONParse(txt);
  if (!parsed.ok) return { ok: false, snippet: txt.slice(0, 1000), status: res.status };
  return { ok: true, json: parsed.json, status: res.status };
}

function sanitizeFilename(n) {
  if (!n) return "download";
  return String(n).replace(/["<>\\\/\r\n]+/g, "_").slice(0, 200);
}

// main handler to run the two-step flow and return structured result
export default {
  async fetch(request) {
    try {
      if (request.method === "OPTIONS") return new Response(null, { headers: CORS_HEADERS });

      const url = new URL(request.url);
      // Accept both GET ?url=... and POST { link: ... }
      let shareLink = null;
      if (request.method === "GET") {
        shareLink = url.searchParams.get("url") || url.searchParams.get("link") || null;
      } else if (request.method === "POST") {
        try {
          const body = await request.json().catch(() => ({}));
          shareLink = body.link || body.url || null;
        } catch (e) {
          shareLink = null;
        }
      }

      if (!shareLink) {
        return new Response(JSON.stringify({ error: "No share URL provided. Use ?url=... or POST {link:...}" }), {
          status: 400, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }

      // Step 1: initial fetch and token extraction
      const first = await fetchTextWithHeaders(shareLink, DISGUISE_HEADERS);
      if (!first.ok) {
        return new Response(JSON.stringify({ error: "Failed initial fetch", status: first.status, snippet: first.text?.slice?.(0,200) }), {
          status: 502, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }

      const finalUrl = first.url;
      const surl = (() => {
        try { return new URL(finalUrl).searchParams.get("surl"); } catch (e) { return null; }
      })();
      if (!surl) {
        // sometimes short url embedded in HTML
        const s = (first.text.match(/shorturl['"]?\s*[:=]\s*['"]([^'"]+)['"]/) || [])[1] || null;
        if (s) { /* use s */ } 
      }

      // Extract tokens robustly from HTML
      const toks = extractTokensFromHtml(first.text);
      let { jsToken, logid, bdstoken, shareid, uk } = toks;

      // If shareid/uk missing, attempt share/init fallback
      if ((!shareid || !uk) && surl) {
        const init = await tryInitApiForShare(surl);
        if (init.ok) {
          shareid = shareid || init.json?.shareid || init.json?.data?.shareid || init.json?.result?.shareid;
          uk = uk || init.json?.uk || init.json?.data?.uk || init.json?.result?.uk;
        } else {
          // keep going; we may still get shareid from /share/list response
        }
      }

      // If jsToken looks like function blob or percent-encoded, decode safely
      if (jsToken) jsToken = decodeJsTokenMaybe(jsToken);

      // Validate essential tokens we need for share/list
      if (!jsToken || !logid) {
        return new Response(JSON.stringify({ error: "Missing tokens: jsToken or logid", debug: { jsToken, logid, bdstoken, shareid, uk, finalUrlSnippet: first.text.slice(0,300) } }), {
          status: 400, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }

      // Step 1b: call share/list
      const listResult = await getShareList(finalUrl, surl, jsToken, logid, bdstoken);
      if (!listResult.ok) {
        return new Response(JSON.stringify({ error: "share/list failed", info: listResult }), {
          status: 502, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }
      const listJson = listResult.json;

      // Try to obtain shareid/uk from the list response if not found earlier
      shareid = shareid || listJson?.shareid || listJson?.data?.shareid || null;
      uk = uk || listJson?.uk || listJson?.data?.uk || null;

      if (!listJson || !listJson.list || !Array.isArray(listJson.list) || listJson.list.length === 0) {
        return new Response(JSON.stringify({ error: "No files returned by share/list", debug: listJson }), {
          status: 404, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }

      // pick first file (you can map all)
      const f = listJson.list[0];
      const fs_id = f?.fs_id || f?.primaryid || null;
      const server_filename = f?.server_filename || f?.filename || "download";

      // If dlink already present in list (sometimes available), use it
      let dlink = f?.dlink || "";

      // Otherwise step 2: call api/download with claim ticket
      if (!dlink) {
        // build params — include shareid/uk if present; some responses include sign/timestamp in listJson or f
        const dlParams = new URLSearchParams({
          app_id: "250528",
          web: "1",
          channel: "dubox",
          clienttype: "0"
        });
        if (shareid) dlParams.set("shareid", String(shareid));
        if (uk) dlParams.set("uk", String(uk));
        if (f?.sign) dlParams.set("sign", String(f.sign));
        if (f?.timestamp) dlParams.set("timestamp", String(f.timestamp));
        if (fs_id) dlParams.set("primaryid", String(fs_id));
        // some variants use 'primaryid' or 'fs_id' names — we've set primaryid

        // call /api/download
        const dlRes = await getDownloadFromApi(dlParams);
        if (!dlRes.ok) {
          // return debug but proceed to try a few more fallbacks
          // fallback 1: check dlRes.json.list[*].dlink
          if (dlRes.json && dlRes.json.list && dlRes.json.list.length) {
            dlink = dlRes.json.list[0]?.dlink || "";
          } else {
            // fallback 2: try a pcs/file endpoint (older)
            try {
              const pcsUrl = `https://pan.t8s.tingyun123.workers.dev/`; // placeholder — not used; skip
            } catch (e) {}
          }
        } else {
          const dlJson = dlRes.json;
          // prefer dlJson.dlink or dlJson.list[0].dlink
          dlink = dlJson?.dlink || (dlJson?.list && dlJson.list[0] && dlJson.list[0].dlink) || "";
        }
      }

      // Final check: if still no dlink, return debug info to let you inspect
      if (!dlink) {
        return new Response(JSON.stringify({
          error: "Failed to obtain final dlink",
          debug: {
            share_link: shareLink,
            finalUrl,
            surl,
            tokens: { jsToken: !!jsToken, logid: !!logid, bdstoken: !!bdstoken, shareid: !!shareid, uk: !!uk },
            listJsonSnippet: listJson ? JSON.stringify(listJson).slice(0,1200) : null
          }
        }), { status: 502, headers: { "Content-Type": "application/json", ...CORS_HEADERS }});
      }

      // Construct proxy_url if you want streaming via worker
      const proxy_url = `https://${new URL(request.url).host}/proxy?url=${encodeURIComponent(dlink)}&file_name=${encodeURIComponent(sanitizeFilename(server_filename))}`;

      // Return the final structured result
      return new Response(JSON.stringify({
        file_name: server_filename,
        download_link: dlink,
        proxy_url,
        file_size: f?.size ? getSize(parseInt(f.size || 0)) : undefined,
        size_bytes: f?.size ? parseInt(f.size || 0) : undefined,
        raw_list_entry: f
      }), { status: 200, headers: { "Content-Type": "application/json", ...CORS_HEADERS }});

    } catch (err) {
      return new Response(JSON.stringify({ error: "Unhandled exception", message: String(err), stack: err?.stack?.slice?.(0,400) }), {
        status: 500, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
      });
    }
  }
};