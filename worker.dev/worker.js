// This is the full code from the open-source file you provided,
// now correctly implementing the two-step link fetching process.

const COOKIE = PANWEB=1; csrfToken=vMnCCwbxddILvcivhZ-sPi1h; browserid=bZ0O46wWYQJoJKinDqLmhQ2kKeqwSt0jaKE2ZgZdv0XIlFXbxvJtCJ_5Odw=; __bid_n=198ca2a99b04cfd1e44207; _ga=GA1.1.107481995.1755738449; _ga_RSNVN63CM3=GS2.1.s1755738448$o1$g1$t1755738527$j60$l0$h0; ndus=Y2cfn3MteHui7_sr4ZPYToUcMZ3KGqEh9dmOsZej; _gcl_au=1.1.773492122.1756712173; lang=pt; _ga_HSVH9T016H=GS2.1.s1757833668$o12$g0$t1757833674$j54$l0$h0; ndut_fmt=8F4D9AFE1C0210D944DFCA4ACC6B8CF1126C5EF550FC2B6E1EEA2CB790BE38B3; _ga_06ZNKL8C2E=GS2.1.s1757870533$o21$g1$t1757871284$j43$l0$h0";

const HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Accept-Encoding": "gzip, deflate, br",
  "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
  "Connection": "keep-alive",
  "DNT": "1",
  "Host": "www.terabox.app",
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
  "Cookie": COOKIE,
};

const DL_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
  "Referer": "https://terabox.com/",
  "DNT": "1",
  "Connection": "keep-alive",
  "Cookie": COOKIE,
};

function getSize(sizeBytes) {
  if (sizeBytes >= 1024 * 1024 * 1024) return `${(sizeBytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  if (sizeBytes >= 1024 * 1024) return `${(sizeBytes / (1024 * 1024)).toFixed(2)} MB`;
  if (sizeBytes >= 1024) return `${(sizeBytes / 1024).toFixed(2)} KB`;
  return `${sizeBytes} bytes`;
}

function findBetween(str, start, end) {
  const startIndex = str.indexOf(start);
  if (startIndex === -1) return "";
  const endIndex = str.indexOf(end, startIndex + start.length);
  if (endIndex === -1) return "";
  return str.slice(startIndex + start.length, endIndex);
}

async function getFileInfo(link, request) {
  try {
    if (!link) return { error: "Link cannot be empty." };

    let response = await fetch(link, { headers: HEADERS, redirect: 'follow' });
    if (!response.ok) return { error: `Failed to fetch link. Status ${response.status}` };

    const finalUrl = response.url;
    const url = new URL(finalUrl);
    const surl = url.pathname.split('/').pop() || url.searchParams.get("surl");
    if (!surl) return { error: "Invalid link. Could not find 'surl'." };

    response = await fetch(finalUrl, { headers: HEADERS });
    const text = await response.text();

    const jsToken = findBetween(text, 'fn%28%22', '%22%29') || findBetween(text, 'jsToken = "', '"');
    const logid = findBetween(text, 'dp-logid=', '&');
    const bdstoken = findBetween(text, 'bdstoken":"', '"');
    if (!jsToken || !logid || !bdstoken) return { error: `Failed to extract required tokens. Cookie might be invalid. jsToken: ${!!jsToken}, logid: ${!!logid}, bdstoken: ${!!bdstoken}` };

    const params = new URLSearchParams({
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      jsToken,
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
    const data = await response.json();
    if (!data || !data.list || !data.list.length || data.errno) {
      return { error: data.errmsg || "Failed to retrieve file list." };
    }

    const fileInfo = data.list[0];
    
    // =================================================================
    // >> THE FIX: Making the second API call to get the real dlink <<
    // =================================================================
    const dlParams = new URLSearchParams({
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      shareid: data.shareid, // Using the "claim ticket"
      uk: data.uk,           // Using the "claim ticket"
      primaryid: fileInfo.fs_id,
      sign: data.sign, // Using the sign from the previous response
      timestamp: data.timestamp, // Using the timestamp from the previous response
    });

    let realDlink = "";
    try {
      // Calling Counter B
      const dlRes = await fetch(`https://www.terabox.app/api/download?${dlParams}`, { headers: HEADERS });
      const dlData = await dlRes.json();
      realDlink = dlData.dlink || "";
    } catch (e) {
      realDlink = ""; // If it fails, we still return other info
    }

    return {
      file_name: fileInfo.server_filename || "",
      download_link: realDlink, // Using the real link
      thumbnail: fileInfo.thumbs?.url3 || "",
      file_size: getSize(parseInt(fileInfo.size || 0)),
      size_bytes: parseInt(fileInfo.size || 0),
      proxy_url: realDlink ? `https://${new URL(request.url).host}/proxy?url=${encodeURIComponent(realDlink)}&file_name=${encodeURIComponent(fileInfo.server_filename || "download")}` : "",
    };
  } catch (error) {
    return { error: `An error occurred: ${error.message}` };
  }
}

// ... (Rest of the code is unchanged) ...
async function proxyDownload(url, fileName, request) {
    try {
        const headers = new Headers(DL_HEADERS);
        const rangeHeader = request.headers.get("Range");
        if (rangeHeader) headers.set("Range", rangeHeader);

        const response = await fetch(url, { headers, redirect: "follow" });
        if (!response.ok && response.status !== 206) {
            return new Response(JSON.stringify({ error: `Failed to fetch download: ${response.status}` }), {
                status: 502,
                headers: { "Content-Type": "application/json" },
            });
        }

        const responseHeaders = new Headers({
            "Cache-Control": "public, max-age=3600",
            "Content-Type": response.headers.get("Content-Type") || "application/octet-stream",
            "Content-Disposition": `inline; filename="${encodeURIComponent(fileName)}"`,
            "Accept-Ranges": "bytes",
        });

        if (response.headers.has("Content-Range")) responseHeaders.set("Content-Range", response.headers.get("Content-Range"));
        if (response.headers.has("Content-Length")) responseHeaders.set("Content-Length", response.headers.get("Content-Length"));

        return new Response(response.body, { status: response.status, headers: responseHeaders });
    } catch (error) {
        return new Response(JSON.stringify({ error: `Proxy error: ${error.message}` }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
        });
    }
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type,Range",
  "Access-Control-Expose-Headers": "Content-Length,Content-Range",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }
    
    // Changed the primary endpoint to GET for easier testing
    if (request.method === "GET" && url.pathname === "/") {
      const link = url.searchParams.get("url");
      if (!link) {
          return new Response(JSON.stringify({ error: "No URL provided. Use ?url=... format." }), {
              status: 400,
              headers: { "Content-Type": "application/json", ...CORS_HEADERS },
          });
      }
      const fileInfo = await getFileInfo(link, request);
      return new Response(JSON.stringify(fileInfo), {
          status: fileInfo.error ? 400 : 200,
          headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      });
    }

    if (request.method === "GET" && url.pathname === "/proxy") {
      const downloadUrl = url.searchParams.get("url");
      const fileName = url.searchParams.get("file_name") || "download";
      if (!downloadUrl) {
        return new Response(JSON.stringify({ error: "No URL provided for proxy." }), {
          status: 400,
          headers: { "Content-Type": "application/json", ...CORS_HEADERS },
        });
      }
      const proxyResponse = await proxyDownload(downloadUrl, fileName, request);
      proxyResponse.headers.set("Access-Control-Allow-Origin", "*");
      return proxyResponse;
    }

    return new Response(JSON.stringify({ error: "Method or path not allowed. Use GET /?url=..." }), {
      status: 405,
      headers: { "Content-Type": "application/json", ...CORS_HEADERS },
    });
  },
};
