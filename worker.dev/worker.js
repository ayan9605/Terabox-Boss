const COOKIE = "<PUT-YOUR-FRESH-COOKIE-HERE>";

const HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  "Connection": "keep-alive",
  "DNT": "1",
  "Cookie": COOKIE
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
    let response = await fetch(link, { headers: HEADERS, redirect: "follow" });
    const finalUrl = response.url;
    const html = await response.text();

    const surl = new URL(finalUrl).searchParams.get("surl");
    if (!surl) return { error: "Invalid link, no surl found." };

    const jsToken = findBetween(html, 'fn%28%22', '%22%29');
    const logid = findBetween(html, 'dp-logid=', '&');
    const bdstoken = findBetween(html, 'bdstoken":"', '"');

    if (!jsToken || !logid || !bdstoken) {
      return { error: "Failed to extract tokens." };
    }

    // Step 1: Get file info + claim ticket
    const listParams = new URLSearchParams({
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      jsToken,
      "dp-logid": logid,
      bdstoken,
      page: "1",
      num: "20",
      site_referer: finalUrl,
      shorturl: surl,
      root: "1,"
    });

    response = await fetch(`https://dm.terabox.app/share/list?${listParams}`, { headers: HEADERS });
    const listData = await response.json();

    if (!listData || !listData.list || !listData.list.length) {
      return { error: "Failed to fetch file list." };
    }

    const file = listData.list[0];
    const { server_filename, fs_id, size, thumbs } = file;

    // Step 2: Claim download ticket
    const dlParams = new URLSearchParams({
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      jsToken,
      "dp-logid": logid,
      type: "dlink",
      vip: "2",
      timestamp: listData.timestamp || Math.floor(Date.now() / 1000),
      sign: listData.sign || "",
      bdstoken,
      fidlist: `[${fs_id}]`,
    });

    const dlResp = await fetch(`https://www.terabox.app/api/download?${dlParams}`, { headers: HEADERS });
    const dlJson = await dlResp.json();

    let dlink = "";
    if (dlJson?.dlink && dlJson.dlink.length > 0) {
      dlink = dlJson.dlink[0].dlink;
    }

    return {
      file_name: server_filename,
      file_size: getSize(parseInt(size || 0)),
      size_bytes: parseInt(size || 0),
      thumbnail: thumbs?.url3 || "",
      download_link: dlink,
      proxy_url: dlink ? `https://${new URL(request.url).host}/proxy?url=${encodeURIComponent(dlink)}&file_name=${encodeURIComponent(server_filename)}` : ""
    };
  } catch (e) {
    return { error: e.message };
  }
}

async function proxyDownload(url, fileName, request) {
  const headers = new Headers(HEADERS);
  const rangeHeader = request.headers.get("Range");
  if (rangeHeader) headers.set("Range", rangeHeader);

  const resp = await fetch(url, { headers, redirect: "follow" });
  return new Response(resp.body, {
    status: resp.status,
    headers: {
      "Content-Type": resp.headers.get("Content-Type") || "application/octet-stream",
      "Content-Disposition": `inline; filename="${encodeURIComponent(fileName)}"`,
      "Accept-Ranges": "bytes",
      "Access-Control-Allow-Origin": "*"
    }
  });
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

    if (request.method === "OPTIONS") return new Response(null, { headers: CORS_HEADERS });

    if (request.method === "GET" && url.pathname === "/get") {
      const link = url.searchParams.get("url");
      if (!link) {
        return new Response(JSON.stringify({ error: "No link provided." }), {
          status: 400, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
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
        return new Response(JSON.stringify({ error: "No URL provided." }), {
          status: 400, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
        });
      }
      return proxyDownload(downloadUrl, fileName, request);
    }

    return new Response(JSON.stringify({ error: "Not found." }), {
      status: 404, headers: { "Content-Type": "application/json", ...CORS_HEADERS }
    });
  }
};