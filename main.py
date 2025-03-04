from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List
import requests
import sqlite3
import time
import threading

app = FastAPI()

# Database setup
DB_FILE = "database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS apps (url TEXT UNIQUE)")
    conn.commit()
    conn.close()

init_db()

class AppData(BaseModel):
    url: str

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    return conn

def ping_apps():
    while True:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT url FROM apps")
        urls = cursor.fetchall()
        conn.close()

        for (url,) in urls:
            try:
                response = requests.get(url, timeout=5)
                print(f"Pinged {url} - Status: {response.status_code}")
            except requests.RequestException:
                print(f"Failed to ping {url}")

        time.sleep(600)  # Ping every 10 minutes

# Background thread for pinging
threading.Thread(target=ping_apps, daemon=True).start()

@app.get("/apps", response_model=List[str])
def get_apps():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM apps")
    urls = [row[0] for row in cursor.fetchall()]
    conn.close()
    return urls

@app.post("/apps")
def add_app(app_data: AppData):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO apps (url) VALUES (?)", (app_data.url,))
        conn.commit()
        return {"message": "App added for pinging."}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="App already exists.")
    finally:
        conn.close()

@app.delete("/apps")
def remove_app(app_data: AppData):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM apps WHERE url = ?", (app_data.url,))
    conn.commit()
    conn.close()
    return {"message": "App removed from pinging."}

@app.get("/")
def root():
    return {"message": "Koyeb App Pinger is running"}
