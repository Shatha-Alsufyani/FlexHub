import os
import httpx
import nbformat as nbf
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Depends, status
from fastapi.responses import FileResponse
import re
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session
from backend.FlexHub_db.database import get_db, User, NotebookSession, init_db
from typing import Optional
from contextlib import asynccontextmanager
load_dotenv()

# Configuration
# The Hub's REST API is served on the Hub's own port (8081 by default), not on
# the public proxy port 8000. This app itself listens on 8000, so pointing
# HUB_API_URL at 8000 makes the app call itself and get its own 404 back.
HUB_API_URL = os.getenv("HUB_API_URL", "http://localhost:8081/hub/api").rstrip("/")
HUB_TOKEN = os.getenv("HUB_TOKEN", "")

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



# Schemas 

class UserRequest(BaseModel):
    Username: str
    Email: EmailStr
    Password: str = Field(..., min_length=8)
    Role: Optional[str] = "user"


@field_validator("Password")
@classmethod
def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Z]", value):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", value):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not re.search(r"\d", value):
            raise ValueError("Password must contain at least one digit.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", value):
            raise ValueError("Password must contain at least one special character.")
        return value    



# Helper Functions
def validate_file_extension(file: UploadFile):
    if not file.filename.endswith(('.py', '.ipynb')):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file type. Only .py and .ipynb files are allowed."
        )

def remove_temp_file(filepath: str):
    """Deletes temporary notebook after download."""
    if os.path.exists(filepath):
        os.remove(filepath)

def require_hub_token():
    """Fails fast with a clear message instead of an opaque 403 from the Hub."""
    if not HUB_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="HUB_TOKEN is not set. Copy .env.example to .env and set it."
        )

def hub_error(response: httpx.Response) -> HTTPException:
    """Turns an upstream Hub failure into an actionable error."""
    if response.status_code == 404:
        try:
            body = response.json()
        except ValueError:
            body = None
        # A genuine Hub 404 looks like {"status": 404, "message": ...}. Anything
        # else means we are not talking to a Hub at all (wrong host/port).
        if isinstance(body, dict) and "status" in body:
            return HTTPException(
                status_code=404,
                detail="No such user or server on JupyterHub. Create the user first via POST /users."
            )
        return HTTPException(
            status_code=502,
            detail=(
                f"No JupyterHub REST API found at {HUB_API_URL}. Check that "
                f"JupyterHub is running and that HUB_API_URL points at the Hub "
                f"port (8081), not at this app's own port. Upstream: {response.text}"
            )
        )
    return HTTPException(
        status_code=response.status_code,
        detail=f"JupyterHub Error: {response.text}"
    )


# User Management Endpoints 
@app.post("/users", summary="Create User", status_code=status.HTTP_201_CREATED)
async def create_user(user_request: UserRequest, db: Session = Depends(get_db)):
    """Creates the user in the DB with email/role, and syncs to JupyterHub if configured."""
    # 1. Check for existing username
    existing_user = db.query(User).filter(User.username == user_request.Username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User '{user_request.Username}' already exists in database."
        )
    
    # 2. Check for existing email if one was provided
    if user_request.Email:
        existing_email = db.query(User).filter(User.email == user_request.Email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{user_request.Email}' is already registered."
            )

    # Note: If adding hashing later, hash user_request.Password here before saving
    new_user = User(
        username=user_request.Username,
        email=user_request.Email,
        hashed_password=user_request.Password,
        role=user_request.Role or "user"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    hub_status = "JupyterHub sync skipped (HUB_TOKEN not configured)"

    # 3. Register with JupyterHub only if a token is present
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

@app.get("/users/{username}", summary="Get User Details")
async def get_user(username: str, db: Session = Depends(get_db)):
    """Reads user details from our DB and status from JupyterHub if configured."""
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found in database."
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
                else:
                    hub_data = f"Hub returned status {response.status_code}"
            except httpx.RequestError as exc:
                hub_data = f"Hub unreachable: {str(exc)}"

    return {
        "username": db_user.username,
        "database_record": {
            "id": db_user.id,
            "role": db_user.role,
            "created_at": db_user.created_at
        },
        "jupyterhub_status": hub_data
    }


# File Management Endpoints
@app.post("/uploadfile/", summary="Upload Script or Notebook")
async def upload_file(file: UploadFile = File(...)):
    validate_file_extension(file)

    return {"filename": file.filename, "status": "uploaded"} 

@app.get("/files", summary="List Files")
async def list_files():
    return {"files": ["file1.txt", "file2.txt", "file3.txt"]} # also need change..

@app.get("/files/{filename}", summary="Get File Metadata")
async def get_file(filename: str):
    if filename not in ["file1.txt", "file2.txt", "file3.txt"]: #change to connect with files inside the database. 
        raise HTTPException(status_code=404, detail="File not found.")
    return {"file": filename}

@app.delete("/files/{filename}", summary="Delete File")
async def delete_file(filename: str):
    return {"message": f"File {filename} deleted successfully."}


# Notebook Conversion Endpoint
@app.post("/convert", summary="Convert .py to .ipynb and Download")
async def convert_python_to_notebook(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...)
):
    validate_file_extension(file)

    # If it's already an ipynb file, return it as is
    if file.filename.endswith(".ipynb"):
        raise HTTPException(status_code=400, detail="File is already a .ipynb notebook.")

    # Read uploaded .py file asynchronously
    content = (await file.read()).decode("utf-8")

    # Generate Notebook Structure
    nb = nbf.v4.new_notebook()
    
    if "# %%" in content:
        raw_cells = content.split("# %%")
        cells = [nbf.v4.new_code_cell(c.strip()) for c in raw_cells if c.strip()]
    else:
        cells = [nbf.v4.new_code_cell(content)]

    nb["cells"] = cells

    # Export to temp file
    base_name = file.filename.rsplit(".", 1)[0]
    output_filename = f"{base_name}.ipynb"
    
    with open(output_filename, "w", encoding="utf-8") as f:
        nbf.write(nb, f)

    # Schedule deletion of temporary file
    background_tasks.add_task(remove_temp_file, output_filename)

    return FileResponse(
        path=output_filename,
        filename=output_filename,
        media_type="application/x-ipynb+json"
    )


# JupyterHub Server Control Endpoints 
@app.post("/users/{username}/server", summary="Start a Notebook Server")
async def start_notebook_server(username: str):
    """Tells JupyterHub to spin up a notebook environment for the user."""
    require_hub_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{HUB_API_URL}/users/{username}/server", 
                headers=HEADERS
            )
            
            if response.status_code in (201, 202):
                return {"message": f"Server is starting for {username}."}
            elif response.status_code == 200 or (
                response.status_code == 400 and "already running" in response.text
            ):
                # JupyterHub 6 reports an already-running server as 400.
                return {"message": f"Server is already running for {username}."}
            else:
                raise hub_error(response)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503, 
                detail=f"Unable to reach JupyterHub server: {str(exc)}"
            )

@app.delete("/users/{username}/server", summary="Stop a Notebook Server")
async def stop_notebook_server(username: str):
    """Shuts down a user's active notebook server."""
    require_hub_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.delete(
                f"{HUB_API_URL}/users/{username}/server", 
                headers=HEADERS
            )
            
            if response.status_code in (202, 204):
                return {"message": f"Server stopped for {username}."}
            else:
                raise hub_error(response)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503, 
                detail=f"Unable to reach JupyterHub server: {str(exc)}"
            )



class LoginRequest(BaseModel):
    Username: str
    Password: str

@app.post("/login")
def login(
    login_request: LoginRequest,
    db: Session = Depends(get_db)
):
    # Find user by username
    user = db.query(User).filter(
        User.username == login_request.Username
    ).first()

    # User does not exist
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password."
        )

    # Check password
    if user.hashed_password != login_request.Password:
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
