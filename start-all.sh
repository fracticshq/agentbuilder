#!/bin/bash

# Function to kill background processes on exit
cleanup() {
    echo "Stopping all services..."
    kill $(jobs -p)
    exit
}

trap cleanup SIGINT SIGTERM

echo "Starting Agent Builder Platform..."

# Start API
echo "Starting API Server..."
cd apps/api
# Check if venv exists and activate
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi
python run.py &
API_PID=$!
cd ../..

# Wait for API to initialize
sleep 2

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
