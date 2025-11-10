# Streaming Debug Guide

## Changes Made

I've added comprehensive console logging to debug the streaming issue:

### 1. Frontend Changes (`apps/widget/src/utils/apiClient.ts`)
Added logging to track:
- Stream request initiation
- Response status
- Each chunk received from server
- SSE data parsing
- Content accumulation
- Final message resolution

### 2. App Component (`apps/widget/src/App.tsx`)
Added logging to track:
- Placeholder message creation
- Stream callback invocations
- Content updates
- Final response

## How to Debug

### Step 1: Open Browser Console
1. Open the widget at http://localhost:5173
2. Open Developer Tools (F12 or Cmd+Option+I on Mac)
3. Go to the Console tab

### Step 2: Send a Test Message
Send any message through the widget and watch the console output.

### Expected Log Flow

If streaming is working, you should see:

```
[App] Adding placeholder message: <messageId>
[App] Calling sendMessage with streaming...
[APIClient] Starting stream with body: {message: "...", ...}
[APIClient] Stream response received: 200 OK
[APIClient] Starting to read stream...
[APIClient] Received chunk: data: {"type":"status","content":"Processing message..."}

[APIClient] Parsing SSE data: {"type":"status","content":"Processing message..."}
[APIClient] Parsed chunk: {type: "status", content: "Processing message..."}
[App] Stream chunk received: {type: "status", content: "Processing message..."}
[App] Status: Processing message...

[APIClient] Received chunk: data: {"type":"content","content":"Hello"}

[APIClient] Parsing SSE data: {"type":"content","content":"Hello"}
[APIClient] Parsed chunk: {type: "content", content: "Hello"}
[App] Stream chunk received: {type: "content", content: "Hello"}
[App] Updating message with content: Hello...

... (more content chunks)

[APIClient] Stream complete
[APIClient] Resolving with final message: {content: "...", citations: [...]}
[App] Stream complete, final response: {content: "...", ...}
```

## Common Issues to Check

### Issue 1: No Stream Response Received
**Symptom:** Log stops at "Starting stream with body"
**Check:**
- Is the API server running on port 8000?
- Check Network tab in DevTools for the request to `/api/v1/messages/stream`
- Check API server logs for errors

### Issue 2: Response Not Text/Event-Stream
**Symptom:** Log shows response but no chunks
**Check:**
- API response headers should include `Content-Type: text/event-stream`
- Check if backend is actually streaming or returning JSON

### Issue 3: Chunks Received But Not Parsed
**Symptom:** Logs show chunks but parsing errors
**Check:**
- SSE format should be: `data: <JSON>\n\n`
- Check if backend is formatting SSE correctly

### Issue 4: Chunks Parsed But UI Not Updating
**Symptom:** Logs show chunks and parsing, but no UI updates
**Check:**
- Is `updateMessage` being called?
- Check Zustand store state
- Check if message ID matches

## Backend Verification

Check API server logs for:
```
stream_message_called message=...
ensuring_memory_initialized
memory_initialized
message_streaming_complete
```

## Quick Test Command

Open browser console and run:
```javascript
fetch('http://localhost:8000/api/v1/messages/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream'
  },
  body: JSON.stringify({
    message: 'test',
    user_id: 'test',
    stream: true
  })
}).then(async (response) => {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    console.log(decoder.decode(value));
  }
});
```

This will show you the raw SSE stream from the backend.

## Next Steps

1. **Test now** - Send a message and check console logs
2. **Compare with expected flow** above
3. **Identify where the flow breaks**
4. **Share console output** for further debugging

## Rollback

If you need to remove the debug logs:
```bash
git checkout apps/widget/src/utils/apiClient.ts
git checkout apps/widget/src/App.tsx
```
