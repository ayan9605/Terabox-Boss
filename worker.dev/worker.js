const BACKEND = "https://filetolinkv5.onrender.com";
const CACHE_VERSION = 'v10-final';
const CACHE_TTL = 7200;

class FileToLinkCDN {
    constructor() {
        this.cache = caches.default;
    }

    async handleRequest(request) {
        try {
            // Handle CORS preflight
            if (request.method === 'OPTIONS') {
                return this.corsResponse();
            }

            const url = new URL(request.url);
            
            // Test endpoint
            if (url.pathname === '/cdn-test') {
                return new Response(JSON.stringify({
                    status: 'CDN Worker Active',
                    version: CACHE_VERSION,
                    backend: BACKEND,
                    timestamp: new Date().toISOString()
                }), {
                    headers: {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    }
                });
            }

            // Only handle download requests
            if (!url.pathname.startsWith('/dl/')) {
                return this.errorResponse(404, 'Endpoint Not Found');
            }

            return await this.handleDownload(request, url);
            
        } catch (error) {
            console.error('Global error:', error);
            return this.errorResponse(500, `CDN Error: ${error.message}`);
        }
    }

    async handleDownload(request, url) {
        const cacheKey = request.url;
        const fileInfo = this.analyzeFile(url.pathname);
        
        // Try cache first
        if (fileInfo.shouldCache) {
            const cached = await this.cache.match(cacheKey);
            if (cached) {
                console.log('Cache HIT:', url.pathname);
                return this.enhanceCachedResponse(cached);
            }
        }

        console.log('Cache MISS:', url.pathname);
        return await this.fetchFromBackend(request, url, cacheKey, fileInfo);
    }

    async fetchFromBackend(request, url, cacheKey, fileInfo) {
        try {
            // Construct the backend URL correctly
            const backendUrl = `${BACKEND}${url.pathname}${url.search}`;
            console.log('Fetching from backend:', backendUrl);
            
            // Create a proper fetch request
            const backendRequest = new Request(backendUrl, {
                method: 'GET',
                headers: {
                    'User-Agent': 'FileToLink-CDN/1.0',
                    'Accept': '*/*'
                }
            });

            const response = await fetch(backendRequest);
            console.log('Backend response status:', response.status);

            if (!response.ok) {
                return this.handleBackendError(response);
            }

            // Cache successful responses
            if (fileInfo.shouldCache && response.status === 200) {
                await this.cacheResponse(cacheKey, response.clone());
            }

            return this.buildResponse(response);
            
        } catch (error) {
            console.error('Backend fetch error:', error);
            return this.errorResponse(503, `Backend unavailable: ${error.message}`);
        }
    }

    analyzeFile(pathname) {
        const extension = this.getFileExtension(pathname);
        const cacheableExtensions = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mp3', 'pdf', 'zip'];
        const shouldCache = cacheableExtensions.includes(extension);
        
        return {
            extension,
            shouldCache
        };
    }

    getFileExtension(pathname) {
        const match = pathname.match(/\.([a-z0-9]+)(?:[\?#]|$)/i);
        return match ? match[1].toLowerCase() : '';
    }

    async cacheResponse(cacheKey, response) {
        try {
            const responseToCache = response.clone();
            const headers = new Headers(responseToCache.headers);
            
            // Set cache headers
            headers.set('Cache-Control', `public, max-age=${CACHE_TTL}`);
            headers.set('CDN-Cache-Control', `public, max-age=${CACHE_TTL}`);
            headers.set('X-CDN-Cache', 'true');
            
            const cacheResponse = new Response(responseToCache.body, {
                status: responseToCache.status,
                statusText: responseToCache.statusText,
                headers: headers
            });

            // Store in cache
            await this.cache.put(cacheKey, cacheResponse);
            console.log('Cached response for:', cacheKey);
            
        } catch (error) {
            console.error('Cache error:', error);
        }
    }

    enhanceCachedResponse(cachedResponse) {
        const headers = new Headers(cachedResponse.headers);
        headers.set('X-CDN-Cache', 'HIT');
        headers.set('X-Cache-Version', CACHE_VERSION);
        
        return new Response(cachedResponse.body, {
            status: cachedResponse.status,
            statusText: cachedResponse.statusText,
            headers: headers
        });
    }

    buildResponse(originResponse) {
        const headers = new Headers(originResponse.headers);
        
        // Add CDN headers
        headers.set('X-CDN-Cache', 'MISS');
        headers.set('X-Cache-Version', CACHE_VERSION);
        headers.set('Access-Control-Allow-Origin', '*');
        
        // Clean headers
        headers.delete('Set-Cookie');
        
        return new Response(originResponse.body, {
            status: originResponse.status,
            statusText: originResponse.statusText,
            headers: headers
        });
    }

    corsResponse() {
        return new Response(null, {
            status: 204,
            headers: {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Max-Age': '86400'
            }
        });
    }

    handleBackendError(response) {
        const errorMap = {
            404: 'File Not Found',
            403: 'Access Denied',
            500: 'Backend Error'
        };
        
        const message = errorMap[response.status] || `Backend Error: ${response.status}`;
        return this.errorResponse(response.status, message);
    }

    errorResponse(status, message) {
        return new Response(JSON.stringify({
            error: true,
            message: message,
            code: status,
            timestamp: new Date().toISOString(),
            cdn: 'FileToLink-CDN',
            backend: BACKEND
        }), {
            status: status,
            headers: {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
        });
    }
}

// Create instance
const cdn = new FileToLinkCDN();

// Event listener
addEventListener('fetch', event => {
    event.respondWith(cdn.handleRequest(event.request));
});