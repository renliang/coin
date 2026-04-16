"""Uvicorn entry point: python -m api."""

import os

import uvicorn

from api.app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("API_HOST", "127.0.0.1")
    port_s = os.environ.get("API_PORT", "8000")
    try:
        port = int(port_s)
    except ValueError:
        port = 8000
    uvicorn.run(app, host=host, port=port)
