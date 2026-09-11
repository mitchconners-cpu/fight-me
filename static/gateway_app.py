from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os

app = FastAPI(title="Mobile Gateway App")

@app.get("/", response_class=HTMLResponse)
async def serve_mobile_ui():
    file_path = "index.html.mobile-page"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Mobile UI file not found.")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("manifest.json", media_type="application/json")

@app.get("/api/status")
async def api_status():
    return {"status": "running", "default_chat_id": 42}
