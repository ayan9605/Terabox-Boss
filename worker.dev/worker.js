const COOKIE = "<your_cookie_here>"; // fresh PANWEB + ndus cookie

const HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  "Connection": "keep-alive",
  "DNT": "1",
  "Cookie": COOKIE,
};

function getSize(sizeBytes) {
  if (sizeBytes >= 1024 * 1024 * 1024) return `${(sizeBytes / (1024 ** 3)).toFixed(2)} GB`;
  if (sizeBytes >= 1024 * 1024) return `${(sizeBytes / (1024 ** 2)).toFixed(2)} MB`;
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
    const surl = new URL(finalUrl).searchParams.get("surl");
    if (!surl) return { error: "Invalid link." };

    const html = await response.text();
    const jsToken = findBetween(html, 'fn%28%22', '%22%29');
    const logid = findBetween(html, 'dp-logid=', '&');
    const bdstoken = findBetween(html, 'bdstoken":"', '"');

    // Hit /share/list to grab claim ticket details
    const params = new URLSearchParams({
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      jsToken,
      "dp-logid": logid,
      page: "1",
      num: "20",
      shorturl: surl,
      root: "1,",
      site_referer: finalUrl,
    });

    response = await fetch(`https://dm.terabox.app/share/list?${params}`, { headers: HEADERS });
    const data = await response.json();
    if (!data || !data.list || !data.list.length) return { error: "Failed to fetch list." };

    const file = data.list[0];
    const fs_id = file.fs_id;
    const sign = data.sign;
    const timestamp = data.timestamp;

    // --- Attempt C: mimic Download button ---
    const pC = new URLSearchParams({
      app_id: "250528",
      web: "1",
      channel: "dubox",
      clienttype: "0",
      jsToken,
      "dp-logid": logid,
      fidlist: `[${fs_id}]`,
      type: "dlink",
      vip: "2",
      sign,
      timestamp,
      need_speed: "0",
      bdstoken,
    });

    const dRes = await fetch(`https://www.1024terabox.com/api/download?${pC}`, { headers: HEADERS });
    const dJson = await dRes.json();
    const dlink = dJson?.dlink?.[0]?.dlink || "";

    return {
      file_name: file.server_filename,
      thumbnail: file.thumbs?.url3 || "",
      file_size: getSize(parseInt(file.size || 0)),
      size_bytes: parseInt(file.size || 0),
      dlink,
      proxy_url: dlink
        ? `https://${new URL(request.url).host}/proxy?url=${encodeURIComponent(dlink)}&file_name=${encodeURIComponent(file.server_filename)}`
        : "",
    };
  } catch (err) {
    return { error: `Exception: ${err.message}` };
  }
}

async function proxyDownload(url, fileName, request) {
  const headers = new Headers(HEADERS);
  const rangeHeader = request.headers.get("Range");
  if (rangeHeader) headers.set("Range", rangeHeader);

  const response = await fetch(url, { headers, redirect: "follow" });
  if (!response.ok && response.status !== 206) {
    return new Response(JSON.stringify({ error: "Proxy fetch failed." }), { status: 502 });
  }

  const responseHeaders = new Headers({
    "Content-Type": response.headers.get("Content-Type") || "application/octet-stream",
    "Content-Disposition": `inline; filename="${encodeURIComponent(fileName)}"`,
    "Accept-Ranges": "bytes",
  });
  if (response.headers.has("Content-Range")) responseHeaders.set("Content-Range", response.headers.get("Content-Range"));
  if (response.headers.has("Content-Length")) responseHeaders.set("Content-Length", response.headers.get("Content-Length"));

  return new Response(response.body, { status: response.status, headers: responseHeaders });
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

    if (request.method === "OPTIONS") return new Response(null, { headers: CORS_HEADERS });

    if (request.method === "POST" && url.pathname === "/") {
      const { link } = await request.json();
      if (!link) return new Response(JSON.stringify({ error: "No link provided." }), { status: 400 });
      const fileInfo = await getFileInfo(link, request);
      return new Response(JSON.stringify(fileInfo), {
        status: fileInfo.error ? 400 : 200,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      });
    }

    if (request.method === "GET" && url.pathname === "/proxy") {
      const downloadUrl = url.searchParams.get("url");
      const fileName = url.searchParams.get("file_name") || "download";
      if (!downloadUrl) return new Response(JSON.stringify({ error: "No proxy URL." }), { status: 400 });
      const proxyResponse = await proxyDownload(downloadUrl, fileName, request);
      proxyResponse.headers.set("Access-Control-Allow-Origin", "*");
      return proxyResponse;
    }

    return new Response(JSON.stringify({ error: "Not allowed." }), { status: 405, headers: CORS_HEADERS });
  },
};