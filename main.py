import os
import time
import threading  # <--- Make sure this is here and correct!
import logging
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from pymongo import MongoClient, errors

app = FastAPI()

# CORS middleware configuration
origins = [
    "https://pinger-final.vercel.app",  # Your Vercel frontend URL
    "http://localhost:3000",      # For local development
    "http://localhost:1234",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# MongoDB configuration from environment variables
MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGODB_DB_NAME", "koyeb")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
apps_collection = db["apps"]

# Ensure a unique index on the "url" field
apps_collection.create_index("url", unique=True)

class AppData(BaseModel):
    url: str

def ping_apps():
    while True:
        try:
            apps = list(apps_collection.find({}, {"_id": 0, "url": 1}))
        except Exception as e:
            logging.error(f"Error fetching apps: {e}")
            apps = []
        for doc in apps:
            url = doc["url"]
            try:
                response = requests.get(url, timeout=5)
                logging.info(f"Pinged {url} - Status: {response.status_code}")
            except requests.RequestException as e:
                logging.error(f"Failed to ping {url}: {e}")
        time.sleep(600)  # Ping every 10 minutes

# Start the pinging process in a background thread
threading.Thread(target=ping_apps, daemon=True).start()

@app.get("/apps", response_model=List[str])
async def get_apps():
    try:
        apps = list(apps_collection.find({}, {"_id": 0, "url": 1}))
        urls = [doc["url"] for doc in apps]
        return urls
    except Exception as e:
        logging.error(f"Error retrieving apps: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.post("/apps")
async def add_app(app_data: AppData):
    try:
        apps_collection.insert_one({"url": app_data.url})
        logging.info(f"Added app: {app_data.url}")
        return {"message": "App added for pinging."}
    except errors.DuplicateKeyError:
        logging.warning(f"App already exists: {app_data.url}")
        raise HTTPException(status_code=400, detail="App already exists.")
    except Exception as e:
        logging.error(f"Error adding app: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.delete("/apps")
async def remove_app(app_data: AppData):
    try:
        result = apps_collection.delete_one({"url": app_data.url})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="App not found.")
        logging.info(f"Removed app: {app_data.url}")
        return {"message": "App removed from pinging."}
    except Exception as e:
        logging.error(f"Error removing app: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.options("/apps")
async def options_apps(request: Request):
    return {"Allow": "GET, POST, DELETE, OPTIONS"}

@app.get("/backend_url")  # NEW ENDPOINT
async def get_backend_url(request: Request):
    backend_url = str(request.base_url)
    return {"backend_url": backend_url}

@app.get("/")
async def root():
    return {"message": "Koyeb App Pinger is running"}
