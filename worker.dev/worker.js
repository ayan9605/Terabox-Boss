const COOKIE = "<cookie>"; // Replace with your actual cookie

const HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
  "Cookie": COOKIE,
};

const DL_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
  "Referer": "https://terabox.com/",
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
    if (!link || !link.startsWith("http")) {
      return { error: "Invalid link provided." };
    }

    let response = await fetch(link, { headers: HEADERS });
    if (!response.ok) {
      return { error: `Failed to fetch link. Status: ${response.status}` };
    }

    const finalUrl = response.url;
    const url = new URL(finalUrl);
    const surl = url.searchParams.get("surl");
    if (!surl) return { error: "No 'surl' found. Invalid Terabox link." };

    const text = await response.text();
    const jsToken = findBetween(text, 'fn%28%22', '%22%29');
    const logid = findBetween(text, 'dp-logid=', '&');
    const bdstoken = findBetween(text, 'bdstoken":"', '"');

    if (!jsToken || !logid || !bdstoken) {
      return { error: "Failed to extract tokens. Cookie may be invalid or page structure changed." };
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
      root: "1,",
    });

    response = await fetch(`https://dm.terabox.app/share/list?${params}`, { headers: HEADERS });
    if (!response.ok) {
      return { error: `Failed to fetch file list. Status: ${response.status}` };
    }

    const data = await response.json().catch(() => null);
    if (!data || !data.list || !data.list.length) {
      return { error: "No files found or invalid API response." };
    }

    const fileInfo = data.list[0];
    return {
      file_name: fileInfo.server_filename || "unknown",
      download_link: fileInfo.dlink || "",
      thumbnail: fileInfo.thumbs?.url3 || "",
      file_size: getSize(parseInt(fileInfo.size || 0)),
      size_bytes: parseInt(fileInfo.size || 0),
      proxy_url: `https://${new URL(request.url).host}/proxy?url=${encodeURIComponent(fileInfo.dlink)}&file_name=${encodeURIComponent(fileInfo.server_filename || 'download')}`,
    };
  } catch (err) {
    return { error: `Unexpected error: ${err.message}` };
  }
}

async function proxyDownload(url, fileName, request) {
  try {
    if (!url) {
      return new Response(JSON.stringify({ error: "No URL provided for proxy." }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const headers = new Headers(DL_HEADERS);
    const rangeHeader = request.headers.get("Range");
    if (rangeHeader) headers.set("Range", rangeHeader);

    const response = await fetch(url, { headers, redirect: "follow" });
    if (!response.ok && response.status !== 206) {
      return new Response(JSON.stringify({ error: `Download failed. Status: ${response.status}` }), {
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
  } catch (err) {
    return new Response(JSON.stringify({ error: `Proxy error: ${err.message}` }), {
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

    if (request.method === "POST" && url.pathname === "/") {
      try {
        const { link } = await request.json().catch(() => ({}));
        if (!link) {
          return new Response(JSON.stringify({ error: "No link provided." }), { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });
        }

        const fileInfo = await getFileInfo(link, request);
        return new Response(JSON.stringify(fileInfo), {
          status: fileInfo.error ? 400 : 200,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: `Server error: ${err.message}` }), { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });
      }
    }

    if (request.method === "GET" && url.pathname === "/proxy") {
      const downloadUrl = url.searchParams.get("url");
      const fileName = url.searchParams.get("file_name") || "download";
      const proxyResponse = await proxyDownload(downloadUrl, fileName, request);
      CORS_HEADERS["Content-Type"] = proxyResponse.headers.get("Content-Type") || "application/octet-stream";
      proxyResponse.headers.forEach((val, key) => {
        if (!CORS_HEADERS[key]) CORS_HEADERS[key] = val;
      });
      return new Response(proxyResponse.body, { status: proxyResponse.status, headers: { ...Object.fromEntries(proxyResponse.headers), ...CORS_HEADERS } });
    }

    return new Response(JSON.stringify({ error: "Invalid path or method." }), {
      status: 405,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  },
};