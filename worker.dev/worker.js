const COOKIE = "<cookie>"; // 🔥 Replace with your real TeraBox cookie

const HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Accept-Encoding": "gzip, deflate, br",
  "Accept-Language": "en-US,en;q=0.9",
  "Connection": "keep-alive",
  "DNT": "1",
  "Host": "www.terabox.app",
  "Upgrade-Insecure-Requests": "1",
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
  "Cookie": COOKIE,
};

const DL_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.5",
  "Referer": "https://terabox.com/",
  "DNT": "1",
  "Connection": "keep-alive",
  "Upgrade-Insecure-Requests": "1",
  "Cookie": COOKIE,
};

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type,Range",
  "Access-Control-Expose-Headers": "Content-Length,Content-Range"
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

    let response = await fetch(link, { headers: HEADERS });
    if (!response.ok) return { error: `Failed initial fetch. Status ${response.status}` };

    const finalUrl = response.url;
    const url = new URL(finalUrl);
    const surl = url.searchParams.get("surl");
    if (!surl) return { error: "Invalid link format." };

    response = await fetch(finalUrl, { headers: HEADERS });
    const text = await response.text();

    const jsToken = findBetween(text, 'fn%28%22', '%22%29');
    const logid = findBetween(text, 'dp-logid=', '&');
    const bdstoken = findBetween(text, 'bdstoken":"', '"');
    const shareid = findBetween(text, '"shareid":', ',');
    const uk = findBetween(text, '"uk":', ',');

    if (!jsToken || !logid || !bdstoken || !shareid || !uk) {
      return { error: "Failed to extract required tokens." };
    }

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
      root: "1,"
    });

    response = await fetch(`https://dm.terabox.app/share/list?${params}`, { headers: HEADERS });
    const data = await response.json();

    if (!data || !data.list || !data.list.length || data.errno) {
      return { error: data.errmsg || "Failed to fetch file list." };
    }

    const fileInfo = data.list[0];

    // 🔥 Step 2: Grab the real dlink
    const downloadParams = new URLSearchParams({
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      jsToken,
      "dp-logid": logid,
      shareid: shareid.replace(/\D/g, ""), // clean digits only
      uk: uk.replace(/\D/g, ""),
      fs_id: fileInfo.fs_id,
    });

    const downloadResp = await fetch(`https://d.terabox.com/api/download?${downloadParams}`, { headers: HEADERS });
    const downloadData = await downloadResp.json();

    let dlink = "";
    if (downloadData && downloadData.list && downloadData.list.length > 0) {
      dlink = downloadData.list[0].dlink || "";
    }

    return {
      file_name: fileInfo.server_filename || "",
      download_link: dlink,
      thumbnail: fileInfo.thumbs?.url3 || "",
      file_size: getSize(parseInt(fileInfo.size || 0)),
      size_bytes: parseInt(fileInfo.size || 0),
      proxy_url: dlink
        ? `https://${new URL(request.url).host}/proxy?url=${encodeURIComponent(dlink)}&file_name=${encodeURIComponent(fileInfo.server_filename || 'download')}`
        : "",
    };
  } catch (err) {
    return { error: `Error: ${err.message}` };
  }
}

async function proxyDownload(url, fileName, request) {
  try {
    const headers = new Headers(DL_HEADERS);
    const rangeHeader = request.headers.get('Range');
    if (rangeHeader) headers.set('Range', rangeHeader);

    const response = await fetch(url, { headers, redirect: 'follow' });

    if (!response.ok && response.status !== 206) {
      return new Response(JSON.stringify({ error: `Download failed. Status ${response.status}` }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }

    const responseHeaders = new Headers({
      'Cache-Control': 'public, max-age=3600',
      'Content-Type': response.headers.get('Content-Type') || 'application/octet-stream',
      'Content-Disposition': `inline; filename="${encodeURIComponent(fileName)}"`,
      'Accept-Ranges': 'bytes'
    });

    if (response.headers.has('Content-Range')) responseHeaders.set('Content-Range', response.headers.get('Content-Range'));
    if (response.headers.has('Content-Length')) responseHeaders.set('Content-Length', response.headers.get('Content-Length'));

    return new Response(response.body, { status: response.status, headers: responseHeaders });
  } catch (err) {
    return new Response(JSON.stringify({ error: `Proxy error: ${err.message}` }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
}

export default {
  async fetch(request) {
    try {
      const url = new URL(request.url);

      if (request.method === "OPTIONS") {
        return new Response(null, { headers: CORS_HEADERS });
      }

      // GET ?url=terabox-link
      if (request.method === "GET" && url.searchParams.get("url")) {
        const link = url.searchParams.get("url");
        const fileInfo = await getFileInfo(link, request);
        return new Response(JSON.stringify(fileInfo), {
          status: fileInfo.error ? 400 : 200,
          headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }

      // POST { link: "terabox-link" }
      if (request.method === "POST" && url.pathname === "/") {
        const { link } = await request.json();
        const fileInfo = await getFileInfo(link, request);
        return new Response(JSON.stringify(fileInfo), {
          status: fileInfo.error ? 400 : 200,
          headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }

      // Proxy download
      if (request.method === "GET" && url.pathname === "/proxy") {
        const downloadUrl = url.searchParams.get("url");
        const fileName = url.searchParams.get("file_name") || "download";
        if (!downloadUrl) {
          return new Response(JSON.stringify({ error: "No URL provided for proxy." }), {
            status: 400,
            headers: { "Content-Type": "application/json", ...CORS_HEADERS }
          });
        }
        const proxyResponse = await proxyDownload(downloadUrl, fileName, request);
        for (const [k, v] of Object.entries(CORS_HEADERS)) {
          proxyResponse.headers.set(k, v);
        }
        return proxyResponse;
      }

      return new Response(JSON.stringify({ error: "Not Found" }), {
        status: 404,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS }
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: `Server error: ${err.message}` }), {
        status: 500,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS }
      });
    }
  }
};