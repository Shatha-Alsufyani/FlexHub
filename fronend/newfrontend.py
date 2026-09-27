import os
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# FLEXHUB CONFIG
# ============================================================

API_URL = os.getenv(
    "FLEXHUB_API_URL",
    "http://localhost:8000"
).rstrip("/")

st.set_page_config(
    page_title="FlexHub",
    page_icon="🔴",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# SESSION STATE (Persists login on page refresh)
# ============================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user_name" not in st.session_state:
    st.session_state.user_name = ""

if "user_email" not in st.session_state:
    st.session_state.user_email = ""

if "user_role" not in st.session_state:
    st.session_state.user_role = "user"

if "navigation" not in st.session_state:
    st.session_state.navigation = "🏠 Dashboard"

# ============================================================
# CUSTOM CSS (Crimson Accent `#cc0000`)
# ============================================================

st.markdown(
    """
    <style>
    .main-title {
        font-size: 38px;
        font-weight: 700;
        margin-bottom: 5px;
    }
    .subtitle {
        font-size: 16px;
        color: #666;
        margin-bottom: 25px;
    }
    .feature-card {
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #eeeeee;
        background-color: white;
        min-height: 150px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }
    .workspace-card {
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #eeeeee;
        background-color: white;
        margin-bottom: 15px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def require_login():
    if not st.session_state.logged_in:
        st.warning("🔐 Please login or create an account from the Sidebar to use this feature.")
        return False
    return True

# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("<h1 style='color:#cc0000;'>🔴 FlexHub</h1>", unsafe_allow_html=True)
    st.caption("Collaborative Data Science Workspace")
    st.markdown("---")

    # ACCOUNT SECTION
    if st.session_state.logged_in:
        st.markdown("### 👤 Account")
        st.success(f"**{st.session_state.user_name}**")
        st.caption(f"📧 {st.session_state.user_email}")
        st.caption(f"Role: {st.session_state.user_role}")

        if st.button("🚪 Logout", use_container_width=True, key="sidebar_logout"):
            st.session_state.logged_in = False
            st.session_state.user_name = ""
            st.session_state.user_email = ""
            st.session_state.user_role = "user"
            st.rerun()

    else:
        st.markdown("### 🔐 Account")
        auth_choice = st.radio("Account Action", ["Login", "Create Account"], key="auth_choice")

        if auth_choice == "Login":
            login_username = st.text_input("Username", key="sidebar_login_username")
            login_password = st.text_input("Password", type="password", key="sidebar_login_password")

            if st.button("🔐 Login", use_container_width=True, key="sidebar_login_submit"):
                if not login_username or not login_password:
                    st.error("Please enter username and password.")
                else:
                    try:
                        response = requests.post(
                            f"{API_URL}/login",
                            json={"Username": login_username, "Password": login_password},
                            timeout=10
                        )
                        if response.status_code == 200:
                            data = response.json()
                            st.session_state.logged_in = True
                            st.session_state.user_name = data.get("username", login_username)
                            st.session_state.user_email = data.get("email", "")
                            st.session_state.user_role = data.get("role", "user")
                            st.success("Login successful!")
                            st.rerun()
                        else:
                            detail = response.json().get("detail", "Invalid credentials.")
                            st.error(detail)
                    except requests.RequestException:
                        st.error("Cannot connect to FlexHub API.")

        else:
            signup_username = st.text_input("Username", key="sidebar_signup_username")
            signup_email = st.text_input("Email", key="sidebar_signup_email")
            signup_password = st.text_input("Password", type="password", key="sidebar_signup_password")

            if st.button("📝 Create Account", use_container_width=True, key="sidebar_signup_submit"):
                if not signup_username or not signup_email or not signup_password:
                    st.error("Please fill in all fields.")
                else:
                    try:
                        response = requests.post(
                            f"{API_URL}/users",
                            json={
                                "Username": signup_username,
                                "Email": signup_email,
                                "Password": signup_password,
                                "Role": "user"
                            },
                            timeout=10
                        )
                        if response.status_code in [200, 201]:
                            st.success("Account created! Please log in.")
                        else:
                            detail = response.json().get("detail", "Could not create account.")
                            st.error(detail)
                    except requests.RequestException:
                        st.error("Cannot connect to FlexHub API.")

    st.markdown("---")

    # NAVIGATION
    st.markdown("### Navigation")
    page = st.radio(
        "Go to",
        ["🏠 Dashboard", "📁 My Workspaces", "📓 Notebooks", "👥 Team", "⚙️ Settings"],
        key="navigation"
    )

# ============================================================
# DASHBOARD
# ============================================================

if page == "🏠 Dashboard":
    st.markdown('<div class="main-title">Welcome to FlexHub 🔴</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Your collaborative workspace for Data Science and Jupyter Notebooks.</div>', unsafe_allow_html=True)

    if st.session_state.logged_in:
        st.success(f"Welcome back, **{st.session_state.user_name}**!")
    else:
        st.info("👋 Welcome! Login from the Sidebar to create workspaces and launch JupyterHub.")

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown('<div class="feature-card"><h3>📁 Workspaces</h3>Create & organize data science projects.</div>', unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="feature-card"><h3>📓 Jupyter Server</h3>Instant auto-launch of JupyterHub environments.</div>', unsafe_allow_html=True)
    with col3:
        st.markdown('<div class="feature-card"><h3>👥 Collaboration</h3>Add team members via name and email.</div>', unsafe_allow_html=True)

# ============================================================
# MY WORKSPACES
# ============================================================

elif page == "📁 My Workspaces":
    st.title("📁 My Workspaces")

    if require_login():
        workspace_id = f"{st.session_state.user_name}_default"
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader(f"Workspace: {st.session_state.user_name}'s Lab")
            st.write("Centralized data directory: `flexhub_data/workspaces`")
        with col2:
            if st.button("🚀 Open JupyterHub Environment", type="primary", use_container_width=True):
                try:
                    res = requests.post(f"{API_URL}/users/{st.session_state.user_name}/server", timeout=15)
                    if res.status_code == 200:
                        data = res.json()
                        url = data.get("url")
                        st.success("Server starting!")
                        st.link_button("🔗 Click to Launch JupyterLab", url, use_container_width=True)
                    else:
                        st.error(f"Backend Error ({res.status_code}): {res.text}")
                except requests.RequestException as e:
                    st.error(f"Could not connect to FastAPI backend: {e}")

        st.markdown("---")
        st.subheader("📁 Upload Files to `flexhub_data`")
        
        uploaded_file = st.file_uploader("Choose a .py or .ipynb file", type=["py", "ipynb"])
        if uploaded_file and st.button("📤 Upload File"):
            try:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                data = {"workspace_id": workspace_id}
                res = requests.post(f"{API_URL}/uploadfile/", files=files, data=data, timeout=15)
                
                if res.status_code == 200:
                    st.success(f"File '{uploaded_file.name}' saved to flexhub_data successfully!")
                else:
                    st.error("Failed to upload file.")
            except requests.RequestException:
                st.error("Backend server connection failed.")

# ============================================================
# NOTEBOOKS & WORKSPACE CREATION
# ============================================================

elif page == "📓 Notebooks":
    st.title("📓 Create Workspace & Launch JupyterHub")

    if require_login():
        st.write("Create a workspace. This will automatically upload your code to `flexhub_data` and start your Jupyter environment.")
        st.markdown("---")

        workspace_name = st.text_input("Workspace Name", placeholder="e.g., Capstone Project")
        uploaded_file = st.file_uploader("Upload Notebook (.ipynb) or Script (.py)", type=["ipynb", "py"])

        st.subheader("👥 Add Team Members (Optional)")
        col_name, col_email = st.columns(2)
        with col_name:
            member_names = st.text_input("Full Names (comma-separated)", placeholder="Zahy Aziz, Yakup Keskindag")
        with col_email:
            member_emails = st.text_input("Emails (comma-separated)", placeholder="zahy@example.com, yakup@example.com")

        if st.button("🚀 Create Workspace & Start Jupyter", type="primary", use_container_width=True):
            if not workspace_name or not uploaded_file:
                st.warning("Please provide both a workspace name and a file.")
            else:
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                    data = {
                        "username": st.session_state.user_name,
                        "workspace_name": workspace_name,
                        "team_members_names": member_names,
                        "team_members_emails": member_emails
                    }
                    
                    res = requests.post(f"{API_URL}/workspaces/create", files=files, data=data, timeout=30)
                    
                    if res.status_code == 200:
                        result = res.json()
                        st.success(f"✅ Workspace '{workspace_name}' created!")
                        st.info(f"📂 Saved file to `flexhub_data`: `{result.get('saved_path')}`")
                        
                        jupyter_url = result.get("jupyter_url", "http://localhost:8001")
                        st.link_button("🔴 Open JupyterHub Workspace", jupyter_url, use_container_width=True)
                    else:
                        st.error(f"Error creating workspace: {res.text}")
                except requests.RequestException as e:
                    st.error(f"Failed to connect to backend: {e}")

# ============================================================
# TEAM
# ============================================================

elif page == "👥 Team":
    st.title("👥 Team Collaboration")

    if require_login():
        st.subheader("Invite Team Member")
        full_name = st.text_input("Full Name")
        email = st.text_input("Email Address")

        if st.button("➕ Add Member", type="primary"):
            if full_name and email:
                st.success(f"Member **{full_name}** ({email}) invited to workspace!")
            else:
                st.warning("Please fill in both Full Name and Email Address.")

# ============================================================
# SETTINGS
# ============================================================

elif page == "⚙️ Settings":
    st.title("⚙️ Settings")

    if require_login():
        st.subheader("Account Details")
        st.text_input("Username", value=st.session_state.user_name, disabled=True)
        st.text_input("Email", value=st.session_state.user_email, disabled=True)
        st.text_input("Backend API URL", value=API_URL, disabled=True)