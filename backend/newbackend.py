import os
import re
import shutil
import uuid
from typing import Optional, List
from contextlib import asynccontextmanager
from dotenv import load_dotenv

import httpx
import nbformat as nbf
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Depends, status, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session
from azure.storage.blob import BlobServiceClient, ContentSettings

from backend.FlexHub_db.database import get_db, User, NotebookSession, FileRecord, init_db

load_dotenv()

# Environment Variables
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "flexhub-uploads")

HUB_API_URL = os.getenv("HUB_API_URL", "http://jupyterhub:8081/hub/api").rstrip("/")
HUB_PROXY_URL = os.getenv("HUB_PROXY_URL", "http://localhost:8001").rstrip("/")
HUB_TOKEN = os.getenv("HUB_TOKEN", "")

BASE_DATA_DIR = os.path.join(os.getcwd(), "flexhub_data")
WORKSPACES_DIR = os.path.join(BASE_DATA_DIR, "workspaces")
os.makedirs(WORKSPACES_DIR, exist_ok=True)

HEADERS = {
    "Authorization": f"Bearer {HUB_TOKEN}",
    "Accept": "application/json",
}

blob_service_client = None
container_client = None

if AZURE_STORAGE_CONNECTION_STRING:
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        if not container_client.exists():
            container_client.create_container()
            print(f"Azure Container '{AZURE_CONTAINER_NAME}' created.")
    except Exception as e:
        print(f"Warning: Failed to connect to Azure Storage: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.db_status = "initialized"
    yield

app = FastAPI(
    title="FlexHub",
    description="Cloud Computing Bootcamp's Capstone Project.",
    version="1.0.0",
    lifespan=lifespan 
)

# Pydantic Schemas
class UserRequest(BaseModel):
    Username: str
    Email: EmailStr
    Password: str = Field(..., min_length=8)
    Role: Optional[str] = "user"

    @field_validator("Password", mode="after")
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Z]", value):
            raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", value):
            raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter.")
        if not re.search(r"\d", value):
            raise HTTPException(status_code=400, detail="Password must contain at least one digit.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", value):
            raise HTTPException(status_code=400, detail="Password must contain at least one special character.")
        return value

class LoginRequest(BaseModel):
    Username: str
    Password: str

class TeamMemberAdd(BaseModel):
    full_name: str
    email: EmailStr

# Helpers
def validate_file_extension(filename: str):
    if not filename.endswith(('.py', '.ipynb', '.csv', '.json', '.txt')):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file type."
        )

def require_hub_token():
    if not HUB_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="HUB_TOKEN is not set in environment."
        )

def hub_error(response: httpx.Response) -> HTTPException:
    if response.status_code == 404:
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and "status" in body:
            return HTTPException(status_code=404, detail="No such user or server on JupyterHub.")
        return HTTPException(status_code=502, detail=f"No JupyterHub REST API found at {HUB_API_URL}.")
    return HTTPException(status_code=response.status_code, detail=f"JupyterHub Error: {response.text}")

async def start_jupyter_server(username: str) -> str:
    if not HUB_TOKEN:
        return f"{HUB_PROXY_URL}/hub/home" 

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(f"{HUB_API_URL}/users/{username}/server", headers=HEADERS)
            if response.status_code in (200, 201, 202) or "already running" in response.text:
                return f"{HUB_PROXY_URL}/hub/home" 
            else:
                raise hub_error(response)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Unable to reach JupyterHub server: {str(exc)}")

# User Endpoints
@app.post("/users", summary="Create User", status_code=status.HTTP_201_CREATED)
async def create_user(user_request: UserRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user_request.Username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail=f"User '{user_request.Username}' already exists.")
    
    if user_request.Email:
        existing_email = db.query(User).filter(User.email == user_request.Email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail=f"Email '{user_request.Email}' is already registered.")

    new_user = User(
        username=user_request.Username,
        email=user_request.Email,
        hashed_password=user_request.Password,
        role=user_request.Role or "user"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    hub_status = "JupyterHub sync skipped"
    if HUB_TOKEN:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(f"{HUB_API_URL}/users/{user_request.Username}", headers=HEADERS)
                if response.status_code in (200, 201):
                    hub_status = "Synced with JupyterHub"
                elif response.status_code == 409:
                    hub_status = "User already exists on JupyterHub"
            except httpx.RequestError as exc:
                hub_status = f"Hub unreachable: {str(exc)}"

    return {
        "message": f"User {new_user.username} created successfully.",
        "user_id": new_user.id,
        "email": new_user.email,
        "role": new_user.role,
        "hub_sync": hub_status
    }

@app.post("/login", summary="User Login")
def login(login_request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == login_request.Username).first()
    if not user or user.hashed_password != login_request.Password:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    return {
        "message": "Login successful",
        "username": user.username,
        "email": user.email,
        "role": user.role
    }

@app.get("/users/{username}", summary="Get User Details")
async def get_user(username: str, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found.")

    hub_data = "No JupyterHub token provided"
    if HUB_TOKEN:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(f"{HUB_API_URL}/users/{username}", headers=HEADERS)
                if response.status_code == 200:
                    hub_data = response.json()
            except httpx.RequestError as exc:
                hub_data = f"Hub unreachable: {str(exc)}"

    return {
        "username": db_user.username,
        "email": db_user.email,
        "database_record": {"id": db_user.id, "role": db_user.role, "created_at": db_user.created_at},
        "jupyterhub_status": hub_data
    }

# Azure Endpoints
@app.post("/upload/azure", summary="Upload file to Private or Shared Azure Blob")
async def upload_to_azure(
    username: str = Form(...),
    privacy: str = Form("private"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not blob_service_client or not container_client:
        raise HTTPException(status_code=500, detail="Azure Storage not configured.")

    prefix = f"private/{username}" if privacy == "private" else "shared"
    blob_name = f"{prefix}/{file.filename}"

    try:
        blob_client = container_client.get_blob_client(blob_name)
        contents = await file.read()
        blob_client.upload_blob(contents, overwrite=True)

        user_record = db.query(User).filter(User.username == username).first()
        user_id = user_record.id if user_record else None

        db_file = FileRecord(user_id=user_id, filename=file.filename, blob_url=blob_client.url, content_type=file.content_type)
        db.add(db_file)
        db.commit()

        return {"message": "File uploaded successfully.", "blob_name": blob_name, "url": blob_client.url}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files/azure", summary="List Private or Shared files in Azure")
async def list_azure_files(username: str = Query(...), scope: str = Query("private")):
    if not blob_service_client or not container_client:
        return {"files": []}

    prefix = f"private/{username}/" if scope == "private" else "shared/"
    file_list = []
    try:
        blobs = container_client.list_blobs(name_starts_with=prefix)
        for blob in blobs:
            clean_name = blob.name.replace(prefix, "")
            if clean_name:
                blob_client = container_client.get_blob_client(blob.name)
                file_list.append({
                    "name": clean_name,
                    "size": round(blob.size / 1024, 2),
                    "url": blob_client.url
                })
        return {"files": file_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# JupyterHub Management Endpoints
@app.post("/users/{username}/server", summary="Start Notebook Server")
async def start_server_endpoint(username: str, db: Session = Depends(get_db)):
    require_hub_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # 1. Ensure user exists on JupyterHub before requesting server start
            await client.post(f"{HUB_API_URL}/users/{username}", headers=HEADERS)

            # 2. Trigger server start
            response = await client.post(f"{HUB_API_URL}/users/{username}/server", headers=HEADERS)
            
            if response.status_code in (200, 201, 202) or (response.status_code == 400 and "already running" in response.text):
                user = db.query(User).filter(User.username == username).first()
                if user:
                    session = db.query(NotebookSession).filter(NotebookSession.user_id == user.id).first()
                    if not session:
                        session = NotebookSession(user_id=user.id, server_status="running")
                        db.add(session)
                    else:
                        session.server_status = "running"
                    db.commit()

                # Always return /hub/home
                return {
                    "message": f"Server started for {username}.",
                    "url": f"{HUB_PROXY_URL}/hub/home"
                }
            else:
                raise hub_error(response)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Unable to reach JupyterHub server: {str(exc)}")

@app.delete("/users/{username}/server", summary="Stop Notebook Server")
async def stop_notebook_server(username: str, db: Session = Depends(get_db)):
    require_hub_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.delete(f"{HUB_API_URL}/users/{username}/server", headers=HEADERS)
            if response.status_code in (202, 204):
                user = db.query(User).filter(User.username == username).first()
                if user:
                    session = db.query(NotebookSession).filter(NotebookSession.user_id == user.id).first()
                    if session:
                        session.server_status = "stopped"
                        db.commit()
                return {"message": f"Server stopped for {username}."}
            else:
                raise hub_error(response)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Unable to reach JupyterHub server: {str(exc)}")