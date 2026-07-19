import express from 'express';
import cors from 'cors';
import session from 'express-session';
import crypto from 'crypto';
import fetch from 'node-fetch';
import 'dotenv/config';
import { handleMcpRequest } from './mcp.js';
import { discoverMcpEndpoints } from './shopify.js';
import {
  insecureLocalDevAuthBypassEnabled,
  isValidMcpServiceAuthorization,
  normalizeShopifyShopDomain,
} from './security.js';

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

const mcpServiceAuthToken = process.env.MCP_SERVICE_AUTH_TOKEN;
const allowInsecureLocalDevMcp = insecureLocalDevAuthBypassEnabled();
if (!mcpServiceAuthToken && !allowInsecureLocalDevMcp) {
  console.error(
    'FATAL: MCP_SERVICE_AUTH_TOKEN must be set. To bypass only for local development, set NODE_ENV=development and SHOPIFY_MCP_ALLOW_INSECURE_LOCAL_DEV=true.',
  );
  process.exit(1);
}
if (allowInsecureLocalDevMcp) {
  console.warn('WARNING: Shopify MCP service authentication bypass is enabled for local development.');
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

function requireMcpServiceAuthentication(req, res, next) {
  if (allowInsecureLocalDevMcp) {
    return next();
  }
  if (!isValidMcpServiceAuthorization(req.get('authorization'), mcpServiceAuthToken)) {
    return res.status(401).json({ error: 'MCP service authentication required' });
  }
  return next();
}

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

// Main MCP Endpoint. Only the configured internal service may invoke it.
app.get('/mcp', requireMcpServiceAuthentication, (_req, res) => {
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

app.post('/mcp', requireMcpServiceAuthentication, async (req, res) => {
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
  let shopUrl;
  const forcedSessionId = req.query.session_id;
  
  if (!req.query.shop) {
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

  try {
    shopUrl = normalizeShopifyShopDomain(req.query.shop);
  } catch (err) {
    return res.status(400).send(err.message);
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
  if (forcedSessionId) {
    req.session.forced_session_id = forcedSessionId;
    sessionStore.set(forcedSessionId, req.session, (err) => {
      if (err) {
        console.error('Failed to save forced Shopify MCP session:', err);
      }
    });
  }

  const authParams = new URLSearchParams({
    client_id: req.session.shopify_client_id || process.env.SHOPIFY_CLIENT_ID,
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

  let endpoints;
  try {
    endpoints = await discoverMcpEndpoints(normalizeShopifyShopDomain(req.session.shop_url));
  } catch (err) {
    return res.status(400).send(err.message);
  }
  if (!endpoints.auth) return res.status(500).send('Auth endpoints not discovered for this shop');
  
  const tokenParams = new URLSearchParams({
    client_id: req.session.shopify_client_id || process.env.SHOPIFY_CLIENT_ID,
    client_secret: req.session.shopify_client_secret || process.env.SHOPIFY_CLIENT_SECRET,
    grant_type: 'authorization_code',
    code: code,
    redirect_uri: process.env.SHOPIFY_REDIRECT_URI || `http://localhost:3005/auth/callback`,
    code_verifier: req.session.code_verifier
  });

  try {
    const response = await fetch(endpoints.auth.token_endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: tokenParams.toString(),
      redirect: 'manual',
    });

    if (response.status >= 300 && response.status < 400) {
      throw new Error('Shopify token endpoint redirect rejected');
    }

    const data = await response.json();
    if (data.error) throw new Error(data.error_description || data.error);

    req.session.customer_access_token = data.access_token;
    if (req.session.forced_session_id) {
      sessionStore.set(req.session.forced_session_id, req.session, (err) => {
        if (err) {
          console.error('Failed to save Shopify customer token for forced session:', err);
        }
      });
    }
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
  const forwardUrl = process.env.SHOPIFY_WEBHOOK_FORWARD_URL;
  if (!forwardUrl) {
    // The bridge is not the source of truth for tenant mapping or catalog
    // state. Acking here would permanently discard a valid Shopify event.
    console.error('SHOPIFY_WEBHOOK_FORWARD_URL is not configured; webhook was not acknowledged', { topic, shop });
    return res.status(503).send('Webhook processing is not configured');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  fetch(forwardUrl, {
    method: 'POST',
    headers: {
      'content-type': req.get('content-type') || 'application/json',
      'x-shopify-hmac-sha256': hmacHeader,
      'x-shopify-topic': topic,
      'x-shopify-shop-domain': shop,
      ...(req.get('x-shopify-webhook-id') ? { 'x-shopify-webhook-id': req.get('x-shopify-webhook-id') } : {}),
    },
    body: req.rawBody,
    redirect: 'manual',
    signal: controller.signal,
  }).then((response) => {
    if (response.status >= 300 && response.status < 400) {
      throw new Error('Webhook forward redirect rejected');
    }
    if (!response.ok) {
      throw new Error(`Webhook forward returned HTTP ${response.status}`);
    }
    console.log('Shopify webhook queued', { topic, shop });
    return res.status(200).send('OK');
  }).catch((err) => {
    console.error('Shopify webhook forwarding failed', { topic, shop, error: err.name });
    return res.status(503).send('Webhook queue unavailable');
  }).finally(() => clearTimeout(timeout));
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
  console.log('Shopify MCP Hub running', { port });
});
