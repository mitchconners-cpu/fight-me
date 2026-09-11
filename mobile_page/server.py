import os
import aiosqlite
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

DB_FILE = "mobile_identity.db"

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                external_id TEXT PRIMARY KEY,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def home():
    return FileResponse("static/index.html")

@app.get("/api/identity/status")
async def identity_status(external_id: str):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT external_id, created_at, last_seen_at FROM users WHERE external_id = ?",
            (external_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No account linked to that identifier.")
    return dict(row)

@app.post("/api/identity/link")
async def link_identity(external_id: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """INSERT INTO users (external_id) VALUES (?)
               ON CONFLICT(external_id) DO UPDATE SET last_seen_at = CURRENT_TIMESTAMP""",
            (external_id,),
        )
        await db.commit()
    return {"status": "linked", "external_id": external_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
