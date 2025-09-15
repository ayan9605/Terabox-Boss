const COOKIE = "PANWEB=1; csrfToken=vMnCCwbxddILvcivhZ-sPi1h; browserid=bZ0O46wWYQJoJKinDqLmhQ2kKeqwSt0jaKE2ZgZdv0XIlFXbxvJtCJ_5Odw=; __bid_n=198ca2a99b04cfd1e44207; _ga=GA1.1.107481995.1755738449; _ga_RSNVN63CM3=GS2.1.s1755738448$o1$g1$t1755738527$j60$l0$h0; ndus=Y2cfn3MteHui7_sr4ZPYToUcMZ3KGqEh9dmOsZej; _gcl_au=1.1.773492122.1756712173; lang=pt; _ga_HSVH9T016H=GS2.1.s1757874649$o13$g0$t1757874691$j18$l0$h0; ndut_fmt=EC92AAB2E90E123BB544F57D03D4EFB6DE9EA78B3A752A86A4A7DBE76998E0FF; _ga_06ZNKL8C2E=GS2.1.s1757870533$o21$g1$t1757874751$j6$l0$h0" // Replace with your actual cookie

const HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Accept-Encoding": "gzip, deflate, br",
  "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
  "Connection": "keep-alive",
  "DNT": "1",
  "Host": "www.terabox.app",
  "Upgrade-Insecure-Requests": "1",
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
  "sec-ch-ua": '"Microsoft Edge";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
  "Sec-Fetch-Dest": "document",
  "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-Site": "none",
  "Sec-Fetch-User": "?1",
  "Cookie": COOKIE,
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": '"Windows"',
};

function getSize(sizeBytes) {
  if (isNaN(sizeBytes) || sizeBytes < 0) return "0 bytes";
  if (sizeBytes >= 1024 * 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  } else if (sizeBytes >= 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024)).toFixed(2)} MB`;
  } else if (sizeBytes >= 1024) {
    return `${(sizeBytes / 1024).toFixed(2)} KB`;
  }
  return `${sizeBytes} bytes`;
}

function findBetween(str, start, end) {
  if (!str) return "";
  const startIndex = str.indexOf(start);
  if (startIndex === -1) return "";
  const endIndex = str.indexOf(end, startIndex + start.length);
  if (endIndex === -1) return "";
  return str.slice(startIndex + start.length, endIndex);
}

async function getFileInfo(link) {
  try {
    if (!link) {
      return { error: "❌ Link cannot be empty." };
    }

    // Step 1: Initial request
    let response = await fetch(link, { headers: HEADERS });
    if (!response.ok) {
      return { error: `❌ Failed to fetch the link. Status code: ${response.status}` };
    }

    const finalUrl = response.url;
    if (!finalUrl.includes("surl=")) {
      return { error: "❌ Invalid Terabox link. 'surl' parameter not found." };
    }

    const url = new URL(finalUrl);
    const surl = url.searchParams.get("surl");
    if (!surl) {
      return { error: "❌ Invalid or unsupported link. 'surl' missing." };
    }

    // Step 2: Fetch share page HTML
    response = await fetch(finalUrl, { headers: HEADERS });
    if (!response.ok) {
      return { error: `❌ Failed to fetch share page. Status code: ${response.status}` };
    }
    const text = await response.text();

    const jsToken = findBetween(text, 'fn%28%22', '%22%29');
    const logid = findBetween(text, 'dp-logid=', '&');
    const bdstoken = findBetween(text, 'bdstoken":"', '"');

    if (!jsToken || !logid || !bdstoken) {
      return { error: "❌ Failed to extract required tokens. Link may be private or expired." };
    }

    // Step 3: Call Terabox list API
    const params = new URLSearchParams({
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      jsToken: jsToken,
      "dp-logid": logid,
      page: "1",
      num: "20",
      by: "name",
      order: "asc",
      site_referer: finalUrl,
      shorturl: surl,
      root: "1,",
    });

    response = await fetch(`https://dm.terabox.app/share/list?${params}`, { headers: HEADERS });
    if (!response.ok) {
      return { error: `❌ Terabox API request failed. Status code: ${response.status}` };
    }

    const data = await response.json();
    if (data.errno) {
      return { error: `❌ Terabox API error: ${data.errmsg || "Unknown error"}` };
    }

    if (!data.list || !data.list.length) {
      return { error: "❌ No files found in this link. It may be empty or restricted." };
    }

    // Step 4: Extract file info
    const fileInfo = data.list[0];
    if (!fileInfo.dlink) {
      return { error: "❌ Failed to retrieve direct link (dlink). File may require login." };
    }

    return {
      file_name: fileInfo.server_filename || "unknown",
      file_size: getSize(parseInt(fileInfo.size || 0)),
      size_bytes: parseInt(fileInfo.size || 0),
      download_link: fileInfo.dlink
    };

  } catch (error) {
    return { error: `❌ Unexpected error: ${error.message}` };
  }
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    // GET /?link=<terabox-link>
    if (request.method === "GET" && url.pathname === "/") {
      const link = url.searchParams.get("link");
      if (!link) {
        return new Response(JSON.stringify({ error: "❌ No link provided in query." }), {
          status: 400,
          headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }

      const fileInfo = await getFileInfo(link);
      return new Response(JSON.stringify(fileInfo), {
        status: fileInfo.error ? 400 : 200,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS }
      });
    }

    return new Response(JSON.stringify({ error: "❌ Method or path not allowed." }), {
      status: 405,
      headers: { "Content-Type": "application/json", ...CORS_HEADERS }
    });
  },
};