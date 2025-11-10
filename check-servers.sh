#!/bin/bash
# Quick server status check

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Server Status Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check API Server (8000)
if lsof -i:8000 | grep -q LISTEN; then
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ API Server (8000) - Running & Healthy"
    else
        echo "⚠️  API Server (8000) - Running but not responding"
    fi
else
    echo "❌ API Server (8000) - Not running"
fi

# Check Admin Dashboard (3001)
if lsof -i:3001 | grep -q LISTEN; then
    if curl -s -I http://localhost:3001 | grep -q "200\|301\|302"; then
        echo "✅ Admin Dashboard (3001) - Running & Healthy"
    else
        echo "⚠️  Admin Dashboard (3001) - Running but not responding"
    fi
else
    echo "❌ Admin Dashboard (3001) - Not running"
fi

# Check Widget (5173)
if lsof -i:5173 | grep -q LISTEN; then
    if curl -s -I http://localhost:5173 | grep -q "200\|301\|302"; then
        echo "✅ Widget (5173) - Running & Healthy"
    else
        echo "⚠️  Widget (5173) - Running but not responding"
    fi
else
    echo "❌ Widget (5173) - Not running"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Access URLs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "API:            http://localhost:8000"
echo "API Docs:       http://localhost:8000/docs"
echo "Admin:          http://localhost:3001"
echo "Widget:         http://localhost:5173"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
