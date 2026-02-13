#!/bin/bash

echo "✅ start-all-window is running"

# Function to kill background processes on exit
cleanup() {
    echo "Stopping all services..."
    kill $(jobs -p)
    exit
}

trap cleanup SIGINT SIGTERM

echo "Starting Agent Builder Platform... (windows version)"

# Start API
echo "Starting API Server..."
cd apps/api
# Check if venv exists and activate
if [ -d ".venv" ]; then
    echo "Activating virtual environment (.venv)..."
    if [ -f ".venv/Scripts/activate" ]; then
        source .venv/Scripts/activate
    else
        source .venv/bin/activate
    fi
elif [ -d "venv" ]; then
    echo "Activating virtual environment (venv)..."
    if [ -f "venv/Scripts/activate" ]; then
        source venv/Scripts/activate
    else
        source venv/bin/activate
    fi
fi

# Run API
python run.py &
API_PID=$!
cd ../..

# Wait for API to initialize
sleep 5

# Start Admin
echo "Starting Admin Dashboard..."
cd apps/admin
npm start &
ADMIN_PID=$!
cd ../..

# Start Widget
echo "Starting Widget..."
cd apps/widget
npm run dev &
WIDGET_PID=$!
cd ../..

echo "All services started!"
echo "----------------------------------------"
echo "API Server:      http://localhost:8000"
echo "Admin Dashboard: http://localhost:3000"
echo "Widget:          http://localhost:5173"
echo "----------------------------------------"
echo "Press Ctrl+C to stop all services."

wait
