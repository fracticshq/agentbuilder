# Server Startup Guide

This guide explains how to start all three servers for the Agent Builder Platform.

## Quick Start (Recommended)

Open **three separate terminal windows/tabs** and run each server in its own terminal:

### Terminal 1: API Server
```bash
cd /Users/anantmendiratta/Desktop/anant2/agent-builder/apps/api
bash start.sh
```

### Terminal 2: Admin Dashboard
```bash
cd /Users/anantmendiratta/Desktop/anant2/agent-builder/apps/admin
PORT=3000 npm start
```

### Terminal 3: Widget
```bash
cd /Users/anantmendiratta/Desktop/anant2/agent-builder/apps/widget
bash start.sh
```

---

## Alternative: Using the start-all.sh Script

You can also use the provided `start-all.sh` script to start all servers:

```bash
cd /Users/anantmendiratta/Desktop/anant2/agent-builder
bash start-all.sh
```

**Note:** This runs all servers in the background. To view logs, check the `logs/` directory.

---

## Checking Server Status

Run the status check script:

```bash
bash /Users/anantmendiratta/Desktop/anant2/agent-builder/check-servers.sh
```

Or manually check ports:

```bash
lsof -i:8000 -i:3000 -i:5173 | grep LISTEN
```

---

## Expected Output

When all servers are running, you should see:

```
✅ API Server (8000) - Running & Healthy
✅ Admin Dashboard (3000) - Running & Healthy  
✅ Widget (5173) - Running & Healthy
```

---

## Access URLs

| Service | URL | Purpose |
|---------|-----|---------|
| **API** | http://localhost:8000 | Backend API |
| **API Docs** | http://localhost:8000/docs | Interactive API documentation |
| **Admin Dashboard** | http://localhost:3000 | Brand & Agent management |
| **Widget** | http://localhost:5173 | Chat widget interface |

---

## Troubleshooting

### Port Already in Use

If you get "port already in use" errors, kill existing processes:

```bash
# Kill specific port
lsof -ti:8000 | xargs kill -9

# Kill all three ports
lsof -ti:8000,3000,5173 | xargs kill -9
```

### Widget Server Keeps Stopping

**Problem:** The widget server keeps getting interrupted.

**Solution:** Run the widget server in its **own dedicated terminal window** (not a shared terminal).

```bash
# Open a new terminal window (Cmd+T in macOS Terminal)
cd /Users/anantmendiratta/Desktop/anant2/agent-builder/apps/widget
bash start.sh

# Leave this terminal open - do not run other commands here
```

### MongoDB Permission Errors

If you see "Unauthorized" errors in the API logs:

**Current Fix:** The system uses `agent-builder` as the system database (configured in `apps/api/.env`):

```bash
MONGO_SYSTEM_DB=agent-builder
```

**Permanent Fix:** Update MongoDB Atlas user permissions to access all databases.

See `MONGODB_PERMISSIONS_FIX.md` for details.

---

## Stopping Servers

### Stop Individual Server

Press `Ctrl+C` in the terminal running that server.

### Stop All Servers

```bash
bash /Users/anantmendiratta/Desktop/anant2/agent-builder/stop-all.sh
```

Or manually:

```bash
lsof -ti:8000,3000,5173 | xargs kill -9
```

---

## Current Server Configuration

| Server | Port | Technology | Auto-reload |
|--------|------|-----------|-------------|
| API | 8000 | FastAPI + Uvicorn | ✅ Yes |
| Admin | 3000 | React + CRA | ✅ Yes |
| Widget | 5173 | React + Vite | ✅ Yes |

All servers support **hot module replacement (HMR)** - changes to code will automatically reload.

---

## Development Workflow

1. **Start all three servers** in separate terminals
2. **Leave them running** during development
3. **Make code changes** - servers will auto-reload
4. **Test changes** in the browser
5. **Stop servers** when done (Ctrl+C or stop-all.sh)

---

## Important Notes

⚠️ **Keep Terminals Open**

Each server terminal must stay open and not be used for other commands. If you run other commands in a server terminal, it may interrupt the server.

✅ **Use Separate Terminals**

- Terminal 1: API server (keep open)
- Terminal 2: Admin dashboard (keep open)
- Terminal 3: Widget (keep open)
- Terminal 4+: For running other commands (tests, checks, etc.)

🔄 **Auto-Reload**

All servers watch for file changes and automatically reload. No need to restart manually after code changes.

---

## Quick Reference

```bash
# Check if servers are running
bash check-servers.sh

# Start all servers
bash start-all.sh

# Stop all servers  
bash stop-all.sh

# View API logs
tail -f apps/api/logs/api.log

# View status
lsof -i:8000 -i:3000 -i:5173 | grep LISTEN
```
