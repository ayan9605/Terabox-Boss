// Cloudflare Worker event listener
addEventListener('fetch', event => {
	event.respondWith(handleRequest(event.request))
  })
  
  // Main function to handle incoming requests
  async function handleRequest(request) {
	const url = new URL(request.url);
	const teraboxUrl = url.searchParams.get('url');
  
	if (!teraboxUrl || !teraboxUrl.includes('terabox.com')) {
	  return new Response(JSON.stringify({ success: false, message: 'Please provide a valid TeraBox URL.' }), {
		headers: { 'Content-Type': 'application/json' },
		status: 400
	  });
	}
  
	try {
	  // =========================================================================
	  // >> THE DISGUISE: A full header set to mimic a real browser <<
	  // =========================================================================
	  const headers = {
		'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
		'Accept': 'application/json, text/plain, */*',
		'Accept-Language': 'en-US,en;q=0.9',
		'Referer': 'https://www.terabox.com/',
		// CRUCIAL: Replace with your fresh, valid 'ndus' cookie value.
		'Cookie': `PANWEB=1; csrfToken=vMnCCwbxddILvcivhZ-sPi1h; browserid=bZ0O46wWYQJoJKinDqLmhQ2kKeqwSt0jaKE2ZgZdv0XIlFXbxvJtCJ_5Odw=; lang=en; __bid_n=198ca2a99b04cfd1e44207; _ga=GA1.1.107481995.1755738449; _ga_RSNVN63CM3=GS2.1.s1755738448$o1$g1$t1755738527$j60$l0$h0; ndus=Y2cfn3MteHui7_sr4ZPYToUcMZ3KGqEh9dmOsZej; _gcl_au=1.1.773492122.1756712173; _ga_HSVH9T016H=GS2.1.s1757611997$o11$g1$t1757612865$j60$l0$h0; ndut_fmt=8B8F16647D98F4F4EC2D30EDB1C09C70D48832BB55F66A577625F80DEEB91119; _ga_06ZNKL8C2E=GS2.1.s1757612014$o17$g1$t1757612889$j55$l0$h0`
	  };
  
	  // =========================================================================
	  // >> STEP 1: Get the final URL and extract tokens <<
	  // =========================================================================
	  const initialResponse = await fetch(teraboxUrl, { headers });
	  const pageText = await initialResponse.text();
	  
	  const jsTokenMatch = pageText.match(/jsToken\s*=\s*"([^"]+)"/);
	  const bdstokenMatch = page-text.match(/"bdstoken":"(.*?)"/);
	  
	  if (!jsTokenMatch || !bdstokenMatch) {
		throw new Error("Could not find jsToken or bdstoken on the page. The cookie is likely invalid.");
	  }
  
	  const jsToken = jsTokenMatch[1];
	  const bdstoken = bdstokenMatch[1];
	  const surl = new URL(initialResponse.url).pathname.split('/').pop();
  
	  // =========================================================================
	  // >> STEP 2: Call the direct data API (/share/list) <<
	  // =========================================================================
	  const params = new URLSearchParams({
		app_id: "250528",
		shorturl: surl,
		root: "1",
		jsToken: jsToken,
		bdstoken: bdstoken
	  });
  
	  const apiUrl = `https://www.terabox.app/share/list?${params}`;
	  const apiResponse = await fetch(apiUrl, { headers });
	  const data = await apiResponse.json();
  
	  if (data.errno !== 0 || !data.list || data.list.length === 0) {
		throw new Error(`The share/list API returned an error: ${data.errmsg || 'Empty list'}`);
	  }
  
	  const fileInfo = data.list[0];
  
	  // =========================================================================
	  // >> STEP 3: Format and return the final data <<
	  // =========================================================================
	  return new Response(JSON.stringify({
		success: true,
		file_name: fileInfo.server_filename,
		download_link: fileInfo.dlink,
		thumbnail: fileInfo.thumbs?.url3,
		size_bytes: parseInt(fileInfo.size, 10)
	  }), {
		headers: { 'Content-Type': 'application/json' },
	  });
  
	} catch (error) {
	  return new Response(JSON.stringify({ success: false, message: error.message }), {
		headers: { 'Content-Type': 'application/json' },
		status: 500
	  });
	}
  }
  
  
