#!/bin/bash

# Admin Dashboard Start Script
cd "$(dirname "$0")"

echo "🚀 Starting Admin Dashboard..."
echo "📂 Working directory: $(pwd)"

PORT=3000 npm start
