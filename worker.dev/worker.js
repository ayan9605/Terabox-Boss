const COOKIE = "<cookie>"; // Replace with your actual cookie

const HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Accept-Encoding": "gzip, deflate, br",
  "Accept-Language": "en-US,en;q=0.9",
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

function getSize(sizeBytes) {
  if (sizeBytes >= 1024 * 1024 * 1024) return `${(sizeBytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  if (sizeBytes >= 1024 * 1024) return `${(sizeBytes / (1024 * 1024)).toFixed(2)} MB`;
  if (sizeBytes >= 1024) return `${(sizeBytes / 1024).toFixed(2)} KB`;
  return `${sizeBytes} bytes`;
}

async function getFileInfo(link, request) {
  try {
    if (!link) return { error: "Link cannot be empty." };

    let response = await fetch(link, { headers: HEADERS });
    if (!response.ok) {
      return { error: `Failed to fetch the initial link. Status: ${response.status}` };
    }

    const finalUrl = response.url;
    const url = new URL(finalUrl);
    const surl = url.searchParams.get("surl");
    if (!surl) return { error: "Invalid link. No surl param found." };

    const text = await response.text();

    // Regex token extraction
    const shareid = text.match(/"shareid":(\d+)/)?.[1];
    const uk = text.match(/"uk":(\d+)/)?.[1];
    const bdstoken = text.match(/"bdstoken":"(.*?)"/)?.[1];
    const jsToken = text.match(/"jsToken":"(.*?)"/)?.[1];
    const logid = text.match(/dp-logid=([0-9]+)/)?.[1];

    if (!shareid || !uk || !bdstoken || !jsToken || !logid) {
      return {
        error: "Failed to extract one or more required tokens.",
        debug: { shareid, uk, bdstoken, jsToken, logid }
      };
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
      shareid,
      uk,
    });

    response = await fetch(`https://dm.terabox.app/share/list?${params}`, { headers: HEADERS });
    const data = await response.json();

    if (!data || !data.list || !data.list.length || data.errno) {
      return { error: data.errmsg || "Failed to retrieve file list." };
    }

    const fileInfo = data.list[0];
    return {
      file_name: fileInfo.server_filename || "",
      download_link: fileInfo.dlink || "",
      thumbnail: fileInfo.thumbs?.url3 || "",
      file_size: getSize(parseInt(fileInfo.size || 0)),
      size_bytes: parseInt(fileInfo.size || 0),
      proxy_url: `https://${new URL(request.url).host}/proxy?url=${encodeURIComponent(fileInfo.dlink)}&file_name=${encodeURIComponent(fileInfo.server_filename || 'download')}`,
    };
  } catch (error) {
    return { error: `An error occurred: ${error.message}` };
  }
}

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

    if (response.headers.has("Content-Range")) {
      responseHeaders.set("Content-Range", response.headers.get("Content-Range"));
    }
    if (response.headers.has("Content-Length")) {
      responseHeaders.set("Content-Length", response.headers.get("Content-Length"));
    }

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
  "Access-Control-Expose-Headers": "Content-Length,Content-Range"
};

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    if (request.method === "GET" && url.pathname === "/file") {
      const link = url.searchParams.get("url");
      if (!link) {
        return new Response(JSON.stringify({ error: "No URL provided." }), {
          status: 400,
          headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }
      const fileInfo = await getFileInfo(link, request);
      return new Response(JSON.stringify(fileInfo), {
        status: fileInfo.error ? 400 : 200,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS }
      });
    }

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
      proxyResponse.headers.set("Access-Control-Allow-Origin", "*");
      proxyResponse.headers.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
      proxyResponse.headers.set("Access-Control-Allow-Headers", "Content-Type,Range");
      proxyResponse.headers.set("Access-Control-Expose-Headers", "Content-Length,Content-Range");
      return proxyResponse;
    }

    return new Response(JSON.stringify({ error: "Endpoint not found." }), {
      status: 404,
      headers: { "Content-Type": "application/json", ...CORS_HEADERS }
    });
  },
};