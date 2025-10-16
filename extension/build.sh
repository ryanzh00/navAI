#!/bin/bash

# Build script for AI Desktop Assistant Chrome Extension

echo "Building AI Desktop Assistant Chrome Extension..."

# Install dependencies if node_modules doesn't exist
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Build the extension
echo "Building extension..."
npm run build

# Check if build was successful
if [ $? -eq 0 ]; then
    echo "✅ Build successful! Extension built in dist/ folder"
    echo ""
    echo "To load the extension in Chrome:"
    echo "1. Open Chrome and go to chrome://extensions/"
    echo "2. Enable 'Developer mode'"
    echo "3. Click 'Load unpacked' and select the 'dist' folder"
    echo ""
    echo "Files in dist/:"
    ls -la dist/
else
    echo "❌ Build failed!"
    exit 1
fi
