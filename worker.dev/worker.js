// Terabox Direct Download Link Extractor with /get endpoint
// Usage: GET /get?link=https://share.terabox.com/s/xxxxx

// 👇 Put your cookie here
const COOKIE = "PANWEB=1; csrfToken=vMnCCwbxddILvcivhZ-sPi1h; browserid=bZ0O46wWYQJoJKinDqLmhQ2kKeqwSt0jaKE2ZgZdv0XIlFXbxvJtCJ_5Odw=; __bid_n=198ca2a99b04cfd1e44207; _ga=GA1.1.107481995.1755738449; _ga_RSNVN63CM3=GS2.1.s1755738448$o1$g1$t1755738527$j60$l0$h0; ndus=Y2cfn3MteHui7_sr4ZPYToUcMZ3KGqEh9dmOsZej; _gcl_au=1.1.773492122.1756712173; lang=pt; _ga_HSVH9T016H=GS2.1.s1757874649$o13$g0$t1757874691$j18$l0$h0; ndut_fmt=EC92AAB2E90E123BB544F57D03D4EFB6DE9EA78B3A752A86A4A7DBE76998E0FF; _ga_06ZNKL8C2E=GS2.1.s1757870533$o21$g1$t1757874751$j6$l0$h0";

const DEFAULT_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
  "Cookie": COOKIE,
  "Accept": "application/json, text/plain, */*",
};

function findBetween(str, start, end) {
  const s = str.indexOf(start);
  if (s === -1) return null;
  const e = str.indexOf(end, s + start.length);
  if (e === -1) return null;
  return str.substring(s + start.length, e);
}

async function fetchJson(url, headers = {}) {
  const res = await fetch(url, { headers, redirect: 'follow' });
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    // return raw text if JSON parse fails
    return text;
  }
}

async function extractAllDownloadLinks(link, opts = {}) {
  const HEADERS = { ...DEFAULT_HEADERS, ...(opts.headers || {}) };

  // Resolve the share page
  const finalRes = await fetch(link, { headers: HEADERS, redirect: 'follow' });
  if (!finalRes.ok) {
    throw new Error(`Failed to fetch share page: ${finalRes.status}`);
  }

  const finalUrl = finalRes.url;
  const text = await finalRes.text();

  // Extract tokens/params
  const jsToken = findBetween(text, 'fn%28%22', '%22%29');
  const logid = findBetween(text, 'dp-logid=', '&');
  const surl = (() => {
    try {
      return new URL(finalUrl).searchParams.get("surl");
    } catch {
      return null;
    }
  })();

  if (!jsToken || !logid || !surl) {
    throw new Error("Failed to extract required params (jsToken | dp-logid | surl).");
  }

  // Request file list (first page)
  const params = new URLSearchParams({
    app_id: "250528",
    web: "1",
    channel: "dubox",
    clienttype: "0",
    jsToken,
    "dp-logid": logid,
    page: "1",
    num: "100",
    shorturl: surl,
    root: "1,",
  });

  const listUrl = `https://dm.terabox.app/share/list?${params.toString()}`;
  const listRes = await fetch(listUrl, { headers: HEADERS, redirect: 'follow' });

  if (!listRes.ok) {
    // Try to surface JSON error if present
    let errorText = await listRes.text();
    try {
      const errJson = JSON.parse(errorText);
      throw new Error(errJson.errmsg || `List fetch failed: ${listRes.status}`);
    } catch {
      throw new Error(`List fetch failed: ${listRes.status}`);
    }
  }

  const data = await listRes.json();

  if (!data || !Array.isArray(data.list) || data.list.length === 0) {
    throw new Error(data?.errmsg || "No files found in this share link.");
  }

  // Map to simpler objects
  const files = data.list.map(file => ({
    file_name: file.server_filename || "unknown",
    download_link: file.dlink || null,
    size_bytes: parseInt(file.size || 0),
  }));

  return files;
}

// --- HTTP handler (Cloudflare Worker / serverless compatible) ---
export default {
  async fetch(request) {
    try {
      const url = new URL(request.url);
      const pathname = url.pathname.replace(/\/+$/, ""); // trim trailing slash
      // Only implement GET /get
      if (request.method === "GET" && pathname === "/get") {
        const link = url.searchParams.get("link");
        if (!link) {
          return new Response(JSON.stringify({ error: "Missing 'link' query parameter." }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
          });
        }

        try {
          const files = await extractAllDownloadLinks(link);
          return new Response(JSON.stringify({ success: true, files }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        } catch (err) {
          return new Response(JSON.stringify({ success: false, error: err.message }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          });
        }
      }

      // Fallback for other routes
      return new Response(JSON.stringify({ error: "Not found. Use GET /get?link=<share_link>" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: `Server error: ${e.message}` }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  }
};