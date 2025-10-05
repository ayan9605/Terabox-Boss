/**
 * Cloudflare Worker: Terabox File Details & Download Link Generator
 * Compatible with Cloudflare Workers (workers.dev) runtime
 * Processes Terabox share links and returns metadata, thumbnail, and direct download link
 */

// ============================================
// CONFIGURATION - Replace with your cookie
// ============================================
const TERABOX_COOKIE = "PANWEB=1; csrfToken=vMnCCwbxddILvcivhZ-sPi1h; browserid=bZ0O46wWYQJoJKinDqLmhQ2kKeqwSt0jaKE2ZgZdv0XIlFXbxvJtCJ_5Odw=; __bid_n=198ca2a99b04cfd1e44207; _ga=GA1.1.107481995.1755738449; _ga_RSNVN63CM3=GS2.1.s1755738448$o1$g1$t1755738527$j60$l0$h0; ndus=Y2cfn3MteHui7_sr4ZPYToUcMZ3KGqEh9dmOsZej; _gcl_au=1.1.773492122.1756712173; lang=pt; g_state={"i_p":1757878043422,"i_l":1}; _ga_HSVH9T016H=GS2.1.s1758354534$o15$g1$t1758354570$j24$l0$h0; _ga_06ZNKL8C2E=deleted; ndut_fmt=1DC9228B02A65EFC0F068ACA36D0DE6FE3E28FEEA18E747D34AE699CC07CC640; _ga_06ZNKL8C2E=GS2.1.s1759659851$o33$g1$t1759659913$j59$l0$h0"; // Example: "lang=en; ndus=YOUR_NDUS_VALUE; BDUSS=YOUR_BDUSS_VALUE;"

// Base URLs for Terabox API endpoints
const BASE_URL = "https://www.1024terabox.com";
const API_BASE = "https://www.1024tera.com";

// ============================================
// MAIN WORKER EVENT HANDLER
// ============================================
export default {
  async fetch(request, env, ctx) {
    // Only allow GET requests
    if (request.method !== "GET") {
      return new Response(
        JSON.stringify({ error: "Method not allowed. Use GET requests only." }),
        { status: 405, headers: { "Content-Type": "application/json" } }
      );
    }

    try {
      const url = new URL(request.url);
      const teraboxUrl = url.searchParams.get("url");

      // Validate input
      if (!teraboxUrl) {
        return new Response(
          JSON.stringify({
            error: "Missing 'url' parameter",
            usage: "Add ?url=https://1024terabox.com/s/YOUR_SHORT_URL"
          }),
          { status: 400, headers: { "Content-Type": "application/json" } }
        );
      }

      console.log("🔄 Processing Terabox URL:", teraboxUrl);

      // Step 1: Extract shorturl from the Terabox link
      const shorturl = extractShortUrl(teraboxUrl);
      if (!shorturl) {
        return new Response(
          JSON.stringify({ error: "Invalid Terabox URL format" }),
          { status: 400, headers: { "Content-Type": "application/json" } }
        );
      }
      console.log("✅ Extracted shorturl:", shorturl);

      // Step 2: Get file metadata from /api/shorturlinfo
      const fileMetadata = await getFileMetadata(shorturl);
      console.log("✅ File metadata retrieved:", fileMetadata.server_filename);

      // Step 3: Get session info (timestamp and sign) from /api/home/info
      const sessionInfo = await getSessionInfo();
      console.log("✅ Session info retrieved - Timestamp:", sessionInfo.timestamp);

      // Step 4: Get direct download link from /api/download
      const downloadInfo = await getDownloadLink(
        fileMetadata.fs_id,
        sessionInfo.sign,
        sessionInfo.timestamp
      );
      console.log("✅ Download link generated successfully");

      // Step 5: Build and return final response
      const response = {
        status: "success",
        file_name: downloadInfo.filename || fileMetadata.server_filename,
        fs_id: fileMetadata.fs_id,
        thumbnail: fileMetadata.thumbnail,
        download_link: downloadInfo.dlink,
        timestamp: sessionInfo.timestamp,
        file_size: fileMetadata.size || "Unknown",
        uk: fileMetadata.uk
      };

      console.log("🎉 Request completed successfully");
      
      return new Response(JSON.stringify(response, null, 2), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      });

    } catch (error) {
      console.error("❌ Error:", error.message);
      return new Response(
        JSON.stringify({
          status: "error",
          message: error.message,
          timestamp: Math.floor(Date.now() / 1000)
        }),
        { status: 500, headers: { "Content-Type": "application/json" } }
      );
    }
  }
};

// ============================================
// HELPER FUNCTIONS
// ============================================

/**
 * Extract shorturl from Terabox share link
 * Supports formats: 
 * - https://1024terabox.com/s/1FynsaKlMsCTsYyXVavGJhg
 * - https://www.terabox.app/s/1FynsaKlMsCTsYyXVavGJhg
 */
function extractShortUrl(url) {
  try {
    const match = url.match(//s/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  } catch (error) {
    console.error("Error extracting shorturl:", error);
    return null;
  }
}

/**
 * Step 2: Fetch file metadata from /api/shorturlinfo
 * Returns: fs_id, filename, thumbnail, uk, size
 */
async function getFileMetadata(shorturl) {
  const endpoint = `${API_BASE}/api/shorturlinfo?shorturl=${shorturl}&root=1`;
  
  console.log("📡 Calling /api/shorturlinfo...");
  
  const response = await fetch(endpoint, {
    method: "GET",
    headers: {
      "Cookie": TERABOX_COOKIE,
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch metadata: ${response.status} ${response.statusText}`);
  }

  const data = await response.json();
  
  // Handle API error responses
  if (data.errno !== 0) {
    throw new Error(`API Error: ${data.errmsg || "Unknown error from shorturlinfo"}`);
  }

  // Extract file info from list
  const fileInfo = data.list && data.list[0];
  if (!fileInfo) {
    throw new Error("No file found in the response");
  }

  return {
    fs_id: fileInfo.fs_id,
    server_filename: fileInfo.server_filename,
    thumbnail: fileInfo.thumbs?.url3 || fileInfo.thumbs?.icon || "",
    uk: data.uk || fileInfo.uk,
    size: fileInfo.size
  };
}

/**
 * Step 3: Get session info (timestamp and sign3) from /api/home/info
 * Returns: timestamp, sign
 */
async function getSessionInfo() {
  const endpoint = `${BASE_URL}/api/home/info`;
  
  console.log("📡 Calling /api/home/info...");
  
  const response = await fetch(endpoint, {
    method: "GET",
    headers: {
      "Cookie": TERABOX_COOKIE,
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch session info: ${response.status} ${response.statusText}`);
  }

  const data = await response.json();
  
  if (data.errno !== 0) {
    throw new Error(`API Error: ${data.errmsg || "Unknown error from home/info"}`);
  }

  return {
    timestamp: data.timestamp,
    sign: data.sign3 || data.sign
  };
}

/**
 * Step 4: Get direct download link from /api/download
 * Returns: dlink, filename
 */
async function getDownloadLink(fs_id, sign, timestamp) {
  const fidlist = `[${fs_id}]`;
  const endpoint = `${BASE_URL}/api/download?sign=${sign}&timestamp=${timestamp}&fidlist=${encodeURIComponent(fidlist)}`;
  
  console.log("📡 Calling /api/download...");
  
  const response = await fetch(endpoint, {
    method: "GET",
    headers: {
      "Cookie": TERABOX_COOKIE,
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch download link: ${response.status} ${response.statusText}`);
  }

  const data = await response.json();
  
  if (data.errno !== 0) {
    throw new Error(`API Error: ${data.errmsg || "Unknown error from download API"}`);
  }

  // Extract download link from response
  const dlinkInfo = data.list && data.list[0];
  if (!dlinkInfo || !dlinkInfo.dlink) {
    throw new Error("Download link not found in response");
  }

  return {
    dlink: dlinkInfo.dlink,
    filename: dlinkInfo.filename || dlinkInfo.server_filename
  };
}