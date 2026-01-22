#!/bin/bash

# Install Backend Dependencies
echo "Installing API dependencies..."
cd apps/api
pip install -r requirements.txt
pip install -e ../../packages/commons
pip install -e ../../packages/memory
pip install -e ../../packages/retrieval
pip install -e ../../packages/llm
cd ../..

# Install Admin Dependencies
echo "Installing Admin dependencies..."
cd apps/admin
npm install --legacy-peer-deps
cd ../..

# Install Widget Dependencies
echo "Installing Widget dependencies..."
cd apps/widget
npm install
cd ../..

echo "All dependencies installed!"
