#!/bin/bash

# IZENIC ImmoAssist Backend - Startup Script
# This script starts the FastAPI development server

echo "🚀 Starting IZENIC ImmoAssist Backend..."
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Virtual environment not activated!"
    echo "Please activate it first:"
    echo "  source venv/bin/activate"
    echo ""
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    echo "Please create a .env file with required environment variables."
    echo "See README.md for details."
    echo ""
    exit 1
fi

# Check if PostgreSQL is running
if ! pg_isready > /dev/null 2>&1; then
    echo "⚠️  PostgreSQL is not running!"
    echo "Please start PostgreSQL before running the application."
    echo ""
    exit 1
fi

echo "✅ Environment checks passed"
echo ""
echo "📡 Starting server at http://localhost:8000"
echo "📚 API docs available at http://localhost:8000/docs"
echo ""

# Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

