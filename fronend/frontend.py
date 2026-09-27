import os
import requests
import streamlit as st
from dotenv import load_dotenv

# Optional Azure Blob Storage import
try:
    from azure.storage.blob import BlobServiceClient
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

API_URL = os.getenv("FLEXHUB_API_URL", "http://localhost:8000").rstrip("/")
AZURE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_CONTAINER_NAME = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "flexhub-uploads")

st.set_page_config(
    page_title="FlexHub Workspace",
    page_icon="🔴",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# SESSION STATE MANAGEMENT
# ============================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user_name" not in st.session_state:
    st.session_state.user_name = ""

if "user_email" not in st.session_state:
    st.session_state.user_email = ""

if "team_members" not in st.session_state:
    st.session_state.team_members = []

if "server_status" not in st.session_state:
    st.session_state.server_status = "Stopped"

if "server_url" not in st.session_state:
    st.session_state.server_url = None

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def upload_to_azure_blob(file, filename):
    """Uploads a file to Azure Blob Storage if configured."""
    if not AZURE_AVAILABLE:
        return False, "azure-storage-blob package is not installed."
    
    if not AZURE_CONNECTION_STRING:
        return False, "AZURE_STORAGE_CONNECTION_STRING is missing in .env."

    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        
        # Create container if it doesn't exist
        try:
            container_client.create_container()
        except Exception:
            pass

        blob_path = f"{st.session_state.user_name}/{filename}"
        blob_client = container_client.get_blob_client(blob_path)
        
        blob_client.upload_blob(file.getvalue(), overwrite=True)
        return True, blob_client.url
    except Exception as e:
        return False, str(e)


def require_login():
    if not st.session_state.logged_in:
        st.warning("🔐 Please login or create an account in the Sidebar to continue.")
        return False
    return True

# ============================================================
# STYLING (Crimson Accent #cc0000)
# ============================================================

st.markdown(
    """
    <style>
    .main-header {
        font-size: 36px;
        font-weight: 800;
        color: #1e293b;
        margin-bottom: 5px;
    }
    .brand-accent {
        color: #cc0000;
    }
    .card {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px;
        background-color: white;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        margin-bottom: 15px;
    }
    .status-running {
        color: #16a34a;
        font-weight: 700;
    }
    .status-stopped {
        color: #dc2626;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ============================================================
# 1. SIDEBAR: AUTHENTICATION & NAVIGATION
# ============================================================

with st.sidebar:
    st.markdown('<h1 class="main-header">Flex<span class="brand-accent">Hub</span></h1>', unsafe_allow_html=True)
    st.caption("Cloud Data Science Workspace")
    st.markdown("---")

    # ACCOUNT SECTION
    if st.session_state.logged_in:
        st.markdown("### 👤 Account")
        st.success(f"Signed in as **{st.session_state.user_name}**")
        st.caption(f"📧 {st.session_state.user_email}")

        if st.button("🚪 Sign Out", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user_name = ""
            st.session_state.user_email = ""
            st.session_state.server_status = "Stopped"
            st.session_state.server_url = None
            st.rerun()
    else:
        st.markdown("### 🔐 Account")
        auth_mode = st.radio("Choose Action", ["Login", "Sign Up"], key="auth_mode")

        if auth_mode == "Login":
            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")

            if st.button("Sign In", use_container_width=True, type="primary"):
                if username and password:
                    try:
                        res = requests.post(f"{API_URL}/login", json={"Username": username, "Password": password}, timeout=10)
                        if res.status_code == 200:
                            data = res.json()
                            st.session_state.logged_in = True
                            st.session_state.user_name = data.get("username", username)
                            st.session_state.user_email = data.get("email", "")
                            st.success("Welcome back!")
                            st.rerun()
                        else:
                            st.error(res.json().get("detail", "Invalid username or password."))
                    except requests.RequestException:
                        st.error("Cannot reach backend server.")
                else:
                    st.warning("Please fill in both fields.")

        else:  # Sign Up
            signup_user = st.text_input("Username", key="signup_user")
            signup_email = st.text_input("Email", key="signup_email")
            signup_pass = st.text_input("Password", type="password", key="signup_pass")

            if st.button("Create Account", use_container_width=True, type="primary"):
                if signup_user and signup_email and signup_pass:
                    try:
                        res = requests.post(
                            f"{API_URL}/users",
                            json={"Username": signup_user, "Email": signup_email, "Password": signup_pass, "Role": "user"},
                            timeout=10
                        )
                        if res.status_code in (200, 201):
                            st.success("Account created! Please Sign In.")
                        else:
                            st.error(res.json().get("detail", "Failed to create account."))
                    except requests.RequestException:
                        st.error("Cannot reach backend server.")
                else:
                    st.warning("Please fill in all fields.")

    st.markdown("---")

    # 5. SIDEBAR NAVIGATION
    st.markdown("### Navigation")
    page = st.radio(
        "Menu",
        ["🏠 Dashboard", "📓 JupyterHub Server", "☁️ Azure File Upload", "👥 Team"],
        key="nav_selection"
    )

# ============================================================
# 4. DASHBOARD PAGE
# ============================================================

if page == "🏠 Dashboard":
    st.markdown('<div class="main-header">Workspace Dashboard</div>', unsafe_allow_html=True)
    st.markdown("Overview of your Jupyter server and project team.")
    st.markdown("---")

    if require_login():
        col1, col2 = st.columns(2)

        # Server Overview Card
        with col1:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.subheader("🖥️ Server Status")
            
            status_class = "status-running" if st.session_state.server_status == "Running" else "status-stopped"
            st.markdown(f"Status: <span class='{status_class}'>{st.session_state.server_status}</span>", unsafe_allow_html=True)
            
            if st.session_state.server_status == "Running" and st.session_state.server_url:
                st.link_button("🚀 Launch JupyterLab Environment", st.session_state.server_url, use_container_width=True)
            else:
                st.info("Start your server from the JupyterHub Server page.")
            
            st.markdown('</div>', unsafe_allow_html=True)

        # Team Overview Card
        with col2:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.subheader("👥 Team Members")
            
            if st.session_state.team_members:
                for idx, member in enumerate(st.session_state.team_members, 1):
                    st.write(f"**{idx}. {member['name']}** — `{member['email']}`")
            else:
                st.caption("No team members added yet. Navigate to 'Team' in the sidebar to invite members.")
            
            st.markdown('</div>', unsafe_allow_html=True)

# ============================================================
# 2. JUPYTERHUB SERVER CONTROL PAGE
# ============================================================

elif page == "📓 JupyterHub Server":
    st.title("📓 JupyterHub Server Control")
    st.write("Manage your personal notebook instance.")
    st.markdown("---")

    if require_login():
        col_start, col_stop = st.columns(2)

        with col_start:
            if st.button("▶️ Start Server", type="primary", use_container_width=True):
                with st.spinner("Spinning up server..."):
                    try:
                        res = requests.post(f"{API_URL}/users/{st.session_state.user_name}/server", timeout=15)
                        if res.status_code == 200:
                            st.session_state.server_status = "Running"
                            st.session_state.server_url = res.json().get("url", f"http://localhost:8001/hub/user/{st.session_state.user_name}/")
                            st.success("Server started successfully!")
                        else:
                            st.error(f"Failed to start server: {res.text}")
                    except requests.RequestException as e:
                        st.error(f"Error connecting to backend: {e}")

        with col_stop:
            if st.button("⏹️ Stop Server", use_container_width=True):
                with st.spinner("Stopping server..."):
                    try:
                        res = requests.delete(f"{API_URL}/users/{st.session_state.user_name}/server", timeout=15)
                        if res.status_code in (200, 202, 204):
                            st.session_state.server_status = "Stopped"
                            st.session_state.server_url = None
                            st.success("Server stopped.")
                        else:
                            st.error(f"Failed to stop server: {res.text}")
                    except requests.RequestException as e:
                        st.error(f"Error connecting to backend: {e}")

        st.markdown("---")
        
        # Launch Button
        if st.session_state.server_status == "Running" and st.session_state.server_url:
            st.success("Your server is ready!")
            st.link_button("🚀 Open Active JupyterLab Environment", st.session_state.server_url, use_container_width=True)
        else:
            st.info("Start your server above to obtain the environment launch link.")
            
# ============================================================
# 3. AZURE BLOB STORAGE UPLOAD & FILE VISIBILITY PAGE
# ============================================================

elif page == "☁️ Azure File Upload":
    st.title("☁️ Azure Blob Storage & File Management")
    st.write("Manage your private uploads and files shared across team members.")
    st.markdown("---")

    if require_login():
        # Upload Form Section
        st.subheader("📤 Upload New File")
        
        col_file, col_access = st.columns([2, 1])
        with col_file:
            uploaded_file = st.file_uploader(
                "Select Python script (.py) or Notebook (.ipynb)", 
                type=["py", "ipynb", "csv", "json", "txt"]
            )
        with col_access:
            privacy_option = st.radio(
                "File Privacy Level",
                ["🔒 Private (Only Me)", "🌐 Shared (Team Members)"],
                help="Private files are stored in your personal directory. Shared files are visible to all team members."
            )

        if uploaded_file and st.button("🚀 Upload File to Azure", type="primary"):
            is_private = "Private" in privacy_option
            prefix = f"private/{st.session_state.user_name}" if is_private else "shared"
            blob_path = f"{prefix}/{uploaded_file.name}"

            with st.spinner("Uploading file to Azure Storage..."):
                # 1. Try uploading to Azure via FastAPI endpoint
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                    data = {
                        "username": st.session_state.user_name,
                        "privacy": "private" if is_private else "shared"
                    }
                    res = requests.post(f"{API_URL}/upload/azure", files=files, data=data, timeout=20)
                    
                    if res.status_code == 200:
                        st.success(f"✅ Uploaded `{uploaded_file.name}` as **{privacy_option}**!")
                    else:
                        st.error(f"Backend upload error ({res.status_code}): {res.text}")
                except requests.RequestException:
                    # 2. Direct Azure SDK Fallback if backend is bypassed
                    if AZURE_AVAILABLE and AZURE_CONNECTION_STRING:
                        try:
                            blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
                            container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
                            
                            if not container_client.exists():
                                container_client.create_container()

                            blob_client = container_client.get_blob_client(blob_path)
                            blob_client.upload_blob(uploaded_file.getvalue(), overwrite=True)
                            st.success(f"✅ Uploaded directly to Azure: `{blob_path}`")
                        except Exception as err:
                            st.error(f"Failed to upload to Azure Storage: {err}")
                    else:
                        st.error("Cannot connect to Azure Storage or FastAPI server.")

        st.markdown("---")

        # Azure Storage Explorer / Viewer
        st.subheader("📂 Azure Blob Files Explorer")

        tab_private, tab_shared = st.tabs(["🔒 My Private Files", "🌐 Shared Team Files"])

        # TAB 1: Private Files
        with tab_private:
            st.caption(f"Files stored in path: `azure://{AZURE_CONTAINER_NAME}/private/{st.session_state.user_name}/`")
            try:
                res = requests.get(
                    f"{API_URL}/files/azure", 
                    params={"username": st.session_state.user_name, "scope": "private"},
                    timeout=10
                )
                if res.status_code == 200:
                    files = res.json().get("files", [])
                    if files:
                        for file_info in files:
                            col_name, col_size, col_link = st.columns([3, 1, 1])
                            col_name.write(f"📄 **{file_info['name']}**")
                            col_size.caption(f"{file_info.get('size', 'N/A')} KB")
                            col_link.link_button("🔗 Open", file_info["url"])
                    else:
                        st.info("You haven't uploaded any private files yet.")
                else:
                    st.info("No private files found or backend listing endpoint offline.")
            except requests.RequestException:
                st.warning("Unable to fetch private file list from server.")

        # TAB 2: Shared Files
        with tab_shared:
            st.caption(f"Files stored in path: `azure://{AZURE_CONTAINER_NAME}/shared/`")
            try:
                res = requests.get(
                    f"{API_URL}/files/azure", 
                    params={"username": st.session_state.user_name, "scope": "shared"},
                    timeout=10
                )
                if res.status_code == 200:
                    files = res.json().get("files", [])
                    if files:
                        for file_info in files:
                            col_name, col_owner, col_link = st.columns([3, 1, 1])
                            col_name.write(f"🌐 **{file_info['name']}**")
                            col_owner.caption(f"Shared File")
                            col_link.link_button("🔗 Open", file_info["url"])
                    else:
                        st.info("No shared team files available.")
                else:
                    st.info("No shared files found.")
            except requests.RequestException:
                st.warning("Unable to fetch shared file list from server.")

# ============================================================
# 5. TEAM MANAGEMENT PAGE
# ============================================================

elif page == "👥 Team":
    st.title("👥 Team Management")
    st.write("Add collaborators to your project workspace.")
    st.markdown("---")

    if require_login():
        st.subheader("➕ Invite Team Member")
        
        with st.form("add_team_form", clear_on_submit=True):
            col_name, col_email = st.columns(2)
            with col_name:
                member_name = st.text_input("Full Name")
            with col_email:
                member_email = st.text_input("Email Address")
            
            submit = st.form_submit_button("Add Member", type="primary")

            if submit:
                if member_name and member_email:
                    new_member = {"name": member_name.strip(), "email": member_email.strip()}
                    st.session_state.team_members.append(new_member)
                    st.success(f"Added **{member_name}** ({member_email}) to your team!")
                    st.rerun()
                else:
                    st.warning("Please provide both Full Name and Email Address.")

        st.markdown("---")
        st.subheader("Current Team Members")
        if st.session_state.team_members:
            for idx, member in enumerate(st.session_state.team_members, 1):
                col_info, col_del = st.columns([4, 1])
                with col_info:
                    st.write(f"**{idx}. {member['name']}** — `{member['email']}`")
                with col_del:
                    if st.button("Remove", key=f"remove_member_{idx}"):
                        st.session_state.team_members.pop(idx - 1)
                        st.rerun()
        else:
            st.info("No members added yet.")