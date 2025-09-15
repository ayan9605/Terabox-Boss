const COOKIE = "<cookie>"; // Replace with your fresh cookie

const HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Accept-Encoding": "gzip, deflate, br",
  "Accept-Language": "en-US,en;q=0.9",
  "Connection": "keep-alive",
  "DNT": "1",
  "Host": "www.terabox.app",
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
  "Cookie": COOKIE,
};

function getSize(sizeBytes) {
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

    // STEP 1: Resolve final link
    let response = await fetch(link, { headers: HEADERS, redirect: "follow" });
    if (!response.ok) {
      return { error: `❌ Failed to fetch the link. Status: ${response.status}` };
    }
    const finalUrl = response.url;

    // STEP 2: Fetch HTML to extract tokens
    const html = await response.text();
    const jsToken = findBetween(html, 'fn%28%22', '%22%29');
    const logid = findBetween(html, 'dp-logid=', '&');
    const bdstoken = findBetween(html, 'bdstoken":"', '"');
    const shareid = findBetween(html, '"shareid":', ',');
    const uk = findBetween(html, '"share_uk":', ',');

    if (!jsToken || !logid || !bdstoken || !shareid || !uk) {
      return { error: "❌ Failed to extract required tokens." };
    }

    // STEP 3: Call share/list API
    const surl = new URL(finalUrl).searchParams.get("surl");
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
      shorturl: surl,
      root: "1,",
    });

    response = await fetch(`https://dm.terabox.app/share/list?${params}`, { headers: HEADERS });
    const data = await response.json();

    if (!data || !data.list || !data.list.length) {
      return { error: "❌ No files found in this link." };
    }

    const fileInfo = data.list[0];
    const fs_id = fileInfo.fs_id;

    // STEP 4: Call sharedownload API
    const body = new URLSearchParams({
      encrypt: "0",
      extra: JSON.stringify({ sekey: decodeURIComponent(COOKIE.split("BDCLND=")[1] || "") }),
      fid_list: `[${fs_id}]`,
      primaryid: shareid,
      uk: uk,
      product: "share",
      type: "nolimit",
    });

    response = await fetch(`https://www.terabox.app/api/sharedownload?app_id=250528&web=1&channel=dubox&clienttype=0`, {
      method: "POST",
      headers: {
        ...HEADERS,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      },
      body,
    });

    const dlData = await response.json();
    if (!dlData || !dlData.list || !dlData.list[0]?.dlink) {
      return { error: "❌ Failed to retrieve direct link (dlink). File may require login." };
    }

    return {
      file_name: fileInfo.server_filename || "unknown",
      file_size: getSize(parseInt(fileInfo.size || 0)),
      size_bytes: parseInt(fileInfo.size || 0),
      dlink: dlData.list[0].dlink,
      thumbnail: fileInfo.thumbs?.url3 || "",
    };
  } catch (err) {
    return { error: `❌ Exception: ${err.message}` };
  }
}

// --- Worker Entrypoint ---
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const link = url.searchParams.get("link");

    if (!link) {
      return new Response(JSON.stringify({ error: "❌ No link provided." }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const info = await getFileInfo(link);
    return new Response(JSON.stringify(info), {
      status: info.error ? 400 : 200,
      headers: { "Content-Type": "application/json" },
    });
  },
};