import express from 'express';
import cors from 'cors';
import session from 'express-session';
import crypto from 'crypto';
import fetch from 'node-fetch';
import 'dotenv/config';
import { handleMcpRequest } from './mcp.js';
import { discoverMcpEndpoints } from './shopify.js';

const app = express();
const port = process.env.PORT || 3005;

// Session store: Redis in production, MemoryStore in development
let sessionStore;
if (process.env.NODE_ENV === 'production') {
  const { createClient } = await import('redis');
  const connectRedisModule = await import('connect-redis');
  const RedisStore = connectRedisModule.default || connectRedisModule.RedisStore;
  const redisClient = createClient({ url: process.env.REDIS_URL || 'redis://localhost:6379' });
  redisClient.on('error', (err) => console.error('Redis session store error:', err));
  await redisClient.connect();
  sessionStore = new RedisStore({ client: redisClient, prefix: 'shopify-session:' });
} else {
  sessionStore = new session.MemoryStore();
}

const sessionSecret = process.env.SESSION_SECRET;
if (!sessionSecret) {
  console.error('FATAL: SESSION_SECRET environment variable is not set');
  process.exit(1);
}

const allowedOrigins = process.env.CORS_ALLOW_ORIGINS
  ? process.env.CORS_ALLOW_ORIGINS.split(',').map(o => o.trim())
  : ['http://localhost:3000', 'http://localhost:8000'];

app.use(cors({ origin: allowedOrigins, credentials: true }));
// Capture raw body for HMAC webhook verification before JSON parsing
app.use(express.json({
  verify: (req, _res, buf) => { req.rawBody = buf; }
}));
app.use(session({
  store: sessionStore,
  secret: sessionSecret,
  resave: false,
  saveUninitialized: true,
  cookie: { secure: process.env.NODE_ENV === 'production', sameSite: 'lax' }
}));

/**
 * Middleware to map x-session-id header to express-session.
 * This allows the Python agent to maintain a persistent session via headers.
 */
app.use((req, res, next) => {
  const sessionId = req.headers['x-session-id'];
  if (sessionId) {
    // Attempt to load session by ID from store
    sessionStore.get(sessionId, (err, sess) => {
      if (sess) {
        req.sessionID = sessionId;
        req.session = sess;
      }
      next();
    });
  } else {
    next();
  }
});

// Helper for PKCE
function base64URLEncode(str) {
  return str.toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');
}

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest();
}

// Main MCP Endpoint
app.get('/mcp', (_req, res) => {
  res.status(200).json({
    service: 'agentbuilder-shopify-mcp',
    endpoint: '/mcp',
    method: 'POST',
    protocol: 'json-rpc',
    status: 'ready',
    example: {
      jsonrpc: '2.0',
      id: 'tools-list',
      method: 'tools/list',
      params: {}
    }
  });
});

app.post('/mcp', async (req, res) => {
  try {
    const response = await handleMcpRequest(req.body, req.session, req.headers);
    res.json(response);
  } catch (err) {
    if (err.name === 'AuthRequiredError') {
      return res.json({
        jsonrpc: '2.0',
        id: req.body.id || null,
        result: {
          content: [{ type: 'text', text: `Authentication required. Please log in: ${err.authUrl}` }],
          isError: true
        }
      });
    }
    console.error('MCP Error:', err);
    const isDev = process.env.NODE_ENV !== 'production';
    res.status(500).json({
      jsonrpc: '2.0',
      id: req.body.id || null,
      error: { code: -32603, message: isDev ? err.message : 'Internal server error' }
    });
  }
});

/**
 * Initiates the OAuth 2.0 PKCE Authorization Code flow.
 */
app.get('/auth/login', async (req, res) => {
  const shopUrl = req.query.shop || process.env.SHOPIFY_SHOP_URL;
  const forcedSessionId = req.query.session_id;
  
  if (!shopUrl) {
    return res.status(400).json({
      service: 'agentbuilder-shopify-mcp',
      endpoint: '/auth/login',
      status: 'missing_shop',
      message: 'Add a Shopify shop domain using the shop query parameter.',
      requiredQuery: {
        shop: 'your-store.myshopify.com'
      },
      example: '/auth/login?shop=your-store.myshopify.com'
    });
  }

  // If session_id is provided, we want to ensure we're using that session
  if (forcedSessionId) {
    req.sessionID = forcedSessionId;
  }

  const endpoints = await discoverMcpEndpoints(shopUrl);
  if (!endpoints.auth) return res.status(500).send('Auth endpoints not discovered for this shop');

  // PKCE Generation
  const codeVerifier = base64URLEncode(crypto.randomBytes(32));
  const codeChallenge = base64URLEncode(sha256(codeVerifier));
  const state = crypto.randomBytes(16).toString('hex');

  // Store in session for callback verification
  req.session.code_verifier = codeVerifier;
  req.session.oauth_state = state;
  req.session.shop_url = shopUrl;

  const authParams = new URLSearchParams({
    client_id: process.env.SHOPIFY_CLIENT_ID,
    scope: 'openid email customer_read_customers customer_read_orders', // Add required scopes
    redirect_uri: process.env.SHOPIFY_REDIRECT_URI || `http://localhost:3005/auth/callback`,
    state: state,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
    response_type: 'code'
  });

  res.redirect(`${endpoints.auth.authorization_endpoint}?${authParams.toString()}`);
});

/**
 * Handles the OAuth 2.0 callback and exchanges the code for a token.
 */
app.get('/auth/callback', async (req, res) => {
  const { code, state, error } = req.query;
  if (error) return res.status(400).send(`Auth Error: ${error}`);
  if (state !== req.session.oauth_state) return res.status(400).send('Invalid state');

  const endpoints = await discoverMcpEndpoints(req.session.shop_url);
  
  const tokenParams = new URLSearchParams({
    client_id: process.env.SHOPIFY_CLIENT_ID,
    client_secret: process.env.SHOPIFY_CLIENT_SECRET, // If required for your app type
    grant_type: 'authorization_code',
    code: code,
    redirect_uri: process.env.SHOPIFY_REDIRECT_URI || `http://localhost:3005/auth/callback`,
    code_verifier: req.session.code_verifier
  });

  try {
    const response = await fetch(endpoints.auth.token_endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: tokenParams.toString()
    });

    const data = await response.json();
    if (data.error) throw new Error(data.error_description || data.error);

    req.session.customer_access_token = data.access_token;
    res.send('Authenticated! You can now close this window.');
  } catch (err) {
    console.error('Token Exchange Error:', err);
    res.status(500).send(`Failed to exchange token: ${err.message}`);
  }
});

/**
 * Shopify webhook receiver.
 * Verifies the X-Shopify-Hmac-SHA256 header against the raw request body using
 * SHOPIFY_WEBHOOK_SECRET (set in Shopify Partner Dashboard → Webhooks → Signing secret).
 * Returns 401 if the signature is missing or invalid — Shopify will retry on non-2xx.
 */
app.post('/webhooks', (req, res) => {
  const webhookSecret = process.env.SHOPIFY_WEBHOOK_SECRET;
  if (!webhookSecret) {
    console.error('SHOPIFY_WEBHOOK_SECRET not set — webhook verification skipped');
    return res.status(500).send('Webhook secret not configured');
  }

  const hmacHeader = req.headers['x-shopify-hmac-sha256'];
  if (!hmacHeader) {
    return res.status(401).send('Missing HMAC header');
  }

  const digest = crypto
    .createHmac('sha256', webhookSecret)
    .update(req.rawBody)
    .digest('base64');

  const digestBuf = Buffer.from(digest);
  const headerBuf = Buffer.from(hmacHeader);

  if (
    digestBuf.length !== headerBuf.length ||
    !crypto.timingSafeEqual(digestBuf, headerBuf)
  ) {
    return res.status(401).send('Invalid HMAC signature');
  }

  const topic = req.headers['x-shopify-topic'] || 'unknown';
  const shop  = req.headers['x-shopify-shop-domain'] || 'unknown';
  console.log(`Shopify webhook received: topic=${topic} shop=${shop}`);

  // TODO: dispatch to topic-specific handlers (e.g. orders/create, products/update)

  res.status(200).send('OK');
});

// Health check
app.get('/', (_req, res) => {
  res.status(200).json({
    service: 'agentbuilder-shopify-mcp',
    status: 'ok',
    endpoints: {
      health: '/health',
      mcp: '/mcp',
      authLogin: '/auth/login'
    }
  });
});

app.get('/health', (req, res) => res.status(200).send('OK'));

app.listen(port, () => {
  console.log(`Shopify MCP Hub running on port ${port}`);
});
