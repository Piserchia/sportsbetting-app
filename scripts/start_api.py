#!/usr/bin/env python3
"""
scripts/start_api.py
Start the FastAPI server.

Usage:
    python scripts/start_api.py
    python scripts/start_api.py --port 8001
    python scripts/start_api.py --no-reload   # for production
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",     type=int,  default=8000)
    parser.add_argument("--host",     type=str,  default="127.0.0.1")
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(
        "backend.api.app:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        log_level="info",
    )
