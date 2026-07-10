/**
 * Cloudflare Worker Proxy for Meta WhatsApp Cloud API
 * ---------------------------------------------------
 * Bypasses Hugging Face Spaces outbound firewall / TLS handshake timeout blocks
 * when communicating with graph.facebook.com.
 *
 * How to Deploy (Takes ~2 minutes & 100% Free on Cloudflare):
 * 
 * 1. Log in to your Cloudflare Dashboard (https://dash.cloudflare.com)
 * 2. Go to "Workers & Pages" -> "Create Application" -> "Create Worker"
 * 3. Give your worker a name (e.g. `whatsapp-meta-proxy`) and click "Deploy"
 * 4. Click "Edit Code", replace the default code with this entire script, and click "Deploy"
 * 5. Copy your new Worker URL (e.g. `https://whatsapp-meta-proxy.yourname.workers.dev`)
 * 6. In your Hugging Face Space Settings -> Variables and Secrets:
 *    Add environment variable:
 *      WHATSAPP_API_BASE_URL = https://whatsapp-meta-proxy.yourname.workers.dev
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Forward path and search params directly to official Meta Graph API
    const targetUrl = `https://graph.facebook.com${url.pathname}${url.search}`;

    // Clone incoming request headers and explicitly override target Host
    const headers = new Headers(request.headers);
    headers.set("Host", "graph.facebook.com");

    const modifiedRequest = new Request(targetUrl, {
      method: request.method,
      headers: headers,
      body: request.method !== "GET" && request.method !== "HEAD" ? request.body : undefined,
      redirect: "follow",
    });

    try {
      const response = await fetch(modifiedRequest);
      return response;
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }
  },
};
