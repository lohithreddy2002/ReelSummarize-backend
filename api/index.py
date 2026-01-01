"""
Vercel Serverless Function Entry Point
Exports the FastAPI app for Vercel deployment
"""
import sys
from pathlib import Path

# Add parent directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the FastAPI app
from main import app

# Vercel expects the app to be named 'app' or 'handler'
# FastAPI apps work directly with Vercel's Python runtime

