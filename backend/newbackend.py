import os
import re
import shutil
import httpx
import nbformat as nbf
from typing import Optional, List
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Depends, status, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session
from backend.FlexHub_db.database import get_db, User, NotebookSession, init_db
import uuid
from azure.storage.blob import BlobServiceClient, ContentSettings
from backend.FlexHub_db.database import get_db, User, NotebookSession, FileRecord, init_db
from fastapi import Form, Query
load_dotenv()


import os
from azure.storage.blob import BlobServiceClient

# 1. Environment Variables (Matching keys)
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "flexhub-uploads")

blob_service_client = None
container_client = None

if AZURE_STORAGE_CONNECTION_STRING:
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        
        # Automatically create container in Azure if it doesn't exist
        if not container_client.exists():
            container_client.create_container()
            print(f"Azure Container '{AZURE_CONTAINER_NAME}' created.")
            
    except Exception as e:
        print(f"Warning: Failed to connect to Azure Storage: {e}")
# Configuration
HUB_API_URL = os.getenv("HUB_API_URL", "http://localhost:8081/hub/api").rstrip("/")
HUB_PROXY_URL = os.getenv("HUB_PROXY_URL", "http://localhost:8001").rstrip("/")
HUB_TOKEN = os.getenv("HUB_TOKEN", "")

BASE_DATA_DIR = os.path.join(os.getcwd(), "flexhub_data")
WORKSPACES_DIR = os.path.join(BASE_DATA_DIR, "workspaces")
os.makedirs(WORKSPACES_DIR, exist_ok=True)

HEADERS = {
    "Authorization": f"Bearer {HUB_TOKEN}",
    "Accept": "application/json",
}

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

class LoginRequest(BaseModel):
    Username: str
    Password: str

class TeamMemberAdd(BaseModel):
    full_name: str
    email: EmailStr

class WorkspaceCreateRequest(BaseModel):
    username: str
    workspace_name: str
    team_members: Optional[List[TeamMemberAdd]] = []


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


# Helpers

def validate_file_extension(filename: str):
    if not filename.endswith(('.py', '.ipynb')):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file type. Only .py and .ipynb files are allowed."
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
            return HTTPException(
                status_code=404,
                detail="No such user or server on JupyterHub."
            )
        return HTTPException(
            status_code=502,
            detail=f"No JupyterHub REST API found at {HUB_API_URL}."
        )
    return HTTPException(
        status_code=response.status_code,
        detail=f"JupyterHub Error: {response.text}"
    )

async def start_jupyter_server(username: str) -> str:
    """Helper to start JupyterHub server for a user and return the user's server URL."""
    if not HUB_TOKEN:
        # Send them to the Home page
        return f"{HUB_PROXY_URL}/hub/home" 

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{HUB_API_URL}/users/{username}/server",
                headers=HEADERS
            )
            if response.status_code in (200, 201, 202) or "already running" in response.text:
                # Send them to the Home page
                return f"{HUB_PROXY_URL}/hub/home" 
            else:
                raise hub_error(response)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Unable to reach JupyterHub server: {str(exc)}"
            )
        
#async def start_jupyter_server(username: str) -> str:
#    """Helper to start JupyterHub server for a user and return the user's server URL."""
#    if not HUB_TOKEN:
#       return f"{HUB_PROXY_URL}/hub/user/{username}/"

#    async with httpx.AsyncClient(timeout=30.0) as client:
#        try:
#            response = await client.post(
#                f"{HUB_API_URL}/users/{username}/server",
#                headers=HEADERS
#            )
#            if response.status_code in (200, 201, 202) or "already running" in response.text:
#                return f"{HUB_PROXY_URL}/hub/user/{username}/"
#            else:
#                raise hub_error(response)
#        except httpx.RequestError as exc:
#            raise HTTPException(
#                status_code=503,
#                detail=f"Unable to reach JupyterHub server: {str(exc)}"
#            )


# User Endpoints

@app.post("/users", summary="Create User", status_code=status.HTTP_201_CREATED)
async def create_user(user_request: UserRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user_request.Username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User '{user_request.Username}' already exists."
        )
    
    if user_request.Email:
        existing_email = db.query(User).filter(User.email == user_request.Email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{user_request.Email}' is already registered."
            )

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
                response = await client.post(
                    f"{HUB_API_URL}/users/{user_request.Username}",
                    headers=HEADERS
                )
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
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password."
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found."
        )

    hub_data = "No JupyterHub token provided"
    if HUB_TOKEN:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{HUB_API_URL}/users/{username}",
                    headers=HEADERS
                )
                if response.status_code == 200:
                    hub_data = response.json()
            except httpx.RequestError as exc:
                hub_data = f"Hub unreachable: {str(exc)}"

    return {
        "username": db_user.username,
        "email": db_user.email,
        "database_record": {
            "id": db_user.id,
            "role": db_user.role,
            "created_at": db_user.created_at
        },
        "jupyterhub_status": hub_data
    }


# Workspace & Jupyter Creation Endpoint

@app.post("/workspaces/create", summary="Create Workspace and Start Jupyter Server")
async def create_workspace(
    username: str = Form(...),
    workspace_name: str = Form(...),
    file: UploadFile = File(...),
    team_members_emails: Optional[str] = Form(None), # Comma separated emails
    team_members_names: Optional[str] = Form(None)   # Comma separated names
):
    """Creates a workspace inside flexhub_data, uploads file, adds team members, and starts JupyterHub."""
    validate_file_extension(file.filename)

    workspace_id = f"{username}_{workspace_name.strip().replace(' ', '_').lower()}"
    target_dir = os.path.join(WORKSPACES_DIR, workspace_id)
    os.makedirs(target_dir, exist_ok=True)

    # Save file to flexhub_data
    file_path = os.path.join(target_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Parse team members
    members = []
    if team_members_emails and team_members_names:
        emails = [e.strip() for e in team_members_emails.split(",") if e.strip()]
        names = [n.strip() for n in team_members_names.split(",") if n.strip()]
        for name, email in zip(names, emails):
            members.append({"full_name": name, "email": email})

    # Auto-start JupyterHub notebook environment
    jupyter_url = await start_jupyter_server(username)

    return {
        "message": f"Workspace '{workspace_name}' created successfully.",
        "workspace_id": workspace_id,
        "saved_path": file_path,
        "team_members": members,
        "jupyter_url": jupyter_url
    }


# File Management Endpoints (flexhub_data Integration)

@app.post("/uploadfile/", summary="Upload File to Workspace")
async def upload_file(workspace_id: str = Form(...), file: UploadFile = File(...)):
    validate_file_extension(file.filename)

    workspace_path = os.path.join(WORKSPACES_DIR, workspace_id)
    os.makedirs(workspace_path, exist_ok=True)

    file_path = os.path.join(workspace_path, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "filename": file.filename,
        "workspace_id": workspace_id,
        "status": "uploaded to flexhub_data"
    }

@app.get("/workspaces/{workspace_id}/files", summary="List Files in Workspace")
async def list_workspace_files(workspace_id: str):
    workspace_path = os.path.join(WORKSPACES_DIR, workspace_id)
    if not os.path.exists(workspace_path):
        raise HTTPException(status_code=404, detail="Workspace not found in flexhub_data.")

    files = [f for f in os.listdir(workspace_path) if os.path.isfile(os.path.join(workspace_path, f))]
    return {"workspace_id": workspace_id, "files": files}

@app.get("/workspaces/{workspace_id}/files/{filename}", summary="Download File")
async def get_workspace_file(workspace_id: str, filename: str):
    file_path = os.path.join(WORKSPACES_DIR, workspace_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found in flexhub_data.")

    return FileResponse(path=file_path, filename=filename)

@app.delete("/workspaces/{workspace_id}/files/{filename}", summary="Delete File")
async def delete_workspace_file(workspace_id: str, filename: str):
    file_path = os.path.join(WORKSPACES_DIR, workspace_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found in flexhub_data.")

    os.remove(file_path)
    return {"message": f"File '{filename}' deleted successfully from flexhub_data."}


@app.post("/upload/azure", summary="Upload file to Private or Shared Azure Blob")
async def upload_to_azure(
    username: str = Form(...),
    privacy: str = Form("private"), # "private" or "shared"
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

        db_file = FileRecord(
            user_id=user_id,
            filename=file.filename,
            blob_url=blob_client.url,
            content_type=file.content_type
        )
        db.add(db_file)
        db.commit()

        return {
            "message": "File uploaded successfully.",
            "blob_name": blob_name,
            "url": blob_client.url
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/files/azure", summary="List Private or Shared files in Azure")
async def list_azure_files(
    username: str = Query(...),
    scope: str = Query("private") # "private" or "shared"
):
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

# Notebook Conversion Endpoint

@app.post("/convert", summary="Convert .py to .ipynb and Download")
async def convert_python_to_notebook(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...)
):
    validate_file_extension(file.filename)

    if file.filename.endswith(".ipynb"):
        raise HTTPException(status_code=400, detail="File is already a .ipynb notebook.")

    content = (await file.read()).decode("utf-8")
    nb = nbf.v4.new_notebook()

    if "# %%" in content:
        raw_cells = content.split("# %%")
        cells = [nbf.v4.new_code_cell(c.strip()) for c in raw_cells if c.strip()]
    else:
        cells = [nbf.v4.new_code_cell(content)]

    nb["cells"] = cells

    base_name = file.filename.rsplit(".", 1)[0]
    output_filename = f"{base_name}.ipynb"
    output_path = os.path.join(BASE_DATA_DIR, output_filename)

    with open(output_path, "w", encoding="utf-8") as f:
        nbf.write(nb, f)

    background_tasks.add_task(os.remove, output_path)

    return FileResponse(
        path=output_path,
        filename=output_filename,
        media_type="application/x-ipynb+json"
    )


# JupyterHub Server Standalone Control

@app.post("/users/{username}/server", summary="Start Notebook Server")
async def start_server_endpoint(username: str, db: Session = Depends(get_db)):
    require_hub_token()
    
    # 1. Ask JupyterHub API to spin up the user server
    async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{HUB_API_URL}/users/{username}/server", 
                    headers=HEADERS
                )
                
                if response.status_code in (201, 202):
                    user = db.query(User).filter(User.username == username).first()
                    if user:
                        session = db.query(NotebookSession).filter(NotebookSession.user_id == user.id).first()
                        if not session:
                            session = NotebookSession(user_id=user.id, server_status="running")
                            db.add(session)
                        else:
                            session.server_status = "running"
                        db.commit()
                    return {"message": f"Server is starting for {username}."}
                elif response.status_code == 200 or (
                    response.status_code == 400 and "already running" in response.text
                ):
                    # JupyterHub 6 reports an already-running server as 400.
                    user = db.query(User).filter(User.username == username).first()
                    if user:
                        session = db.query(NotebookSession).filter(NotebookSession.user_id == user.id).first()
                        if not session:
                            session = NotebookSession(user_id=user.id, server_status="running")
                            db.add(session)
                        else:
                            session.server_status = "running"
                        db.commit()
                    return {"message": f"Server is already running for {username}."}
                else:
                    raise hub_error(response)
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=503, 
                    detail=f"Unable to reach JupyterHub server: {str(exc)}"
                )

            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Could not connect to JupyterHub: {str(e)}"
                )

@app.delete("/users/{username}/server", summary="Stop Notebook Server")
async def stop_notebook_server(username: str, db: Session = Depends(get_db)):
    require_hub_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.delete(
                f"{HUB_API_URL}/users/{username}/server", 
                headers=HEADERS
            )
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
            raise HTTPException(
                status_code=503, 
                detail=f"Unable to reach JupyterHub server: {str(exc)}"
            )

            

@app.post("/upload-file/", summary="Upload file to Azure Blob & Save URL to DB")
async def upload_file(
    file: UploadFile = File(...),
    username: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    if not blob_service_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure Blob Storage is not configured. Set AZURE_STORAGE_CONNECTION_STRING in .env"
        )

    try:
        # Find user ID if username is passed from the frontend
        user_id = None
        if username:
            user_record = db.query(User).filter(User.username == username).first()
            if user_record:
                user_id = user_record.id

        # Unique blob name prevents file collisions in the container
        unique_blob_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=unique_blob_name)

        # Upload file stream to Azure Blob
        file_content = await file.read()
        content_settings = ContentSettings(content_type=file.content_type)
        blob_client.upload_blob(file_content, overwrite=True, content_settings=content_settings)
        file_url = blob_client.url

        # Save record & URL into database
        db_file = FileRecord(
            user_id=user_id,
            filename=file.filename,
            blob_url=file_url,
            content_type=file.content_type
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)

        return {
            "message": "File uploaded successfully!",
            "file_id": db_file.id,
            "filename": db_file.filename,
            "file_url": db_file.blob_url
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Azure Upload Failed: {str(e)}")


@app.get("/files/{username}", summary="Get user files from DB")
def get_user_files(username: str, db: Session = Depends(get_db)):
    user_record = db.query(User).filter(User.username == username).first()
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")

    files = db.query(FileRecord).filter(FileRecord.user_id == user_record.id).all()
    return [
        {
            "id": f.id,
            "filename": f.filename,
            "file_url": f.blob_url,
            "uploaded_at": f.uploaded_at
        }
        for f in files
    ]
