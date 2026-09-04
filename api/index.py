import os
import sys
import traceback
from fastapi import FastAPI
from fastapi.responses import JSONResponse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from backend.api.app import app
except Exception as e:
    err_str = str(e)
    err_tb = traceback.format_exc()
    app = FastAPI(title="TrackShift Error Handler")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    def catch_all(full_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Import error during app startup",
                "message": err_str,
                "traceback": err_tb.splitlines(),
            }
        )
