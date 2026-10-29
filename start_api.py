# Start the News Agent API server
# Run from the daily-news-agent directory:
#   python start_api.py

import sys
import os

# Add src/ to the path so the package resolves
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import uvicorn

if __name__ == "__main__":
    print("🚀 Starting News Agent API on http://localhost:8000")
    print("   Docs: http://localhost:8000/docs")
    uvicorn.run(
        "news_agent.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
