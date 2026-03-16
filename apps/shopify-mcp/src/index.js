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

// Memory store for sessions (use Redis for production)
const sessionStore = new session.MemoryStore();

app.use(cors());
app.use(express.json());
app.use(session({
  store: sessionStore,
  secret: process.env.SESSION_SECRET || 'shopify-mcp-secret',
  resave: false,
  saveUninitialized: true,
  cookie: { secure: false }
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
    res.status(500).json({
      jsonrpc: '2.0',
      id: req.body.id || null,
      error: { code: -32603, message: err.message }
    });
  }
});

/**
 * Initiates the OAuth 2.0 PKCE Authorization Code flow.
 */
app.get('/auth/login', async (req, res) => {
  const shopUrl = req.query.shop || process.env.SHOPIFY_SHOP_URL;
  const forcedSessionId = req.query.session_id;
  
  if (!shopUrl) return res.status(400).send('Missing shop parameter');

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
    redirect_uri: `http://localhost:3005/auth/callback`,
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
    redirect_uri: `http://localhost:3005/auth/callback`,
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

// Health check
app.get('/health', (req, res) => res.status(200).send('OK'));

app.listen(port, () => {
  console.log(`Shopify MCP Hub running on port ${port}`);
});
