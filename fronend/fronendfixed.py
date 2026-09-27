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

BASE_DIR = "flexhub_data"
WORKSPACES_DIR = os.path.join(BASE_DIR, "workspaces")

os.makedirs(WORKSPACES_DIR, exist_ok=True)

st.set_page_config(
    page_title="FlexHub",
    page_icon="🔴",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# SESSION STATE
# ============================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user_name" not in st.session_state:
    st.session_state.user_name = ""

if "user_email" not in st.session_state:
    st.session_state.user_email = ""

if "user_role" not in st.session_state:
    st.session_state.user_role = "user"

if "auth_mode" not in st.session_state:
    st.session_state.auth_mode = "login"

if "navigation" not in st.session_state:
    st.session_state.navigation = "🏠 Dashboard"

if "workspaces" not in st.session_state:
    st.session_state.workspaces = []


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown(
    """
    <style>

    .main-title {
        font-size: 42px;
        font-weight: 700;
        margin-bottom: 5px;
    }

    .subtitle {
        font-size: 18px;
        color: #666;
        margin-bottom: 30px;
    }

    .feature-card {
        padding: 25px;
        border-radius: 15px;
        border: 1px solid #eeeeee;
        background-color: white;
        min-height: 170px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }

    .workspace-card {
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #eeeeee;
        background-color: white;
        margin-bottom: 15px;
    }

    .status-online {
        color: green;
        font-weight: 600;
    }

    .status-offline {
        color: #999;
        font-weight: 600;
    }

    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def go_to_notebooks():
    """Callback to switch navigation to Notebooks safely before widgets render."""
    st.session_state.navigation = "📓 Notebooks"

def require_login():
    """
    Check whether the user is logged in.
    """

    if not st.session_state.logged_in:

        st.warning(
            "🔐 Please login or create an account to use this feature."
        )

        st.info(
            "You can login or create an account from the Sidebar."
        )

        return False

    return True


def save_uploaded_file(uploaded_file, workspace_id):
    """
    Save uploaded file inside the workspace directory.
    """

    workspace_path = os.path.join(
        WORKSPACES_DIR,
        workspace_id
    )

    os.makedirs(workspace_path, exist_ok=True)

    file_path = os.path.join(
        workspace_path,
        uploaded_file.name
    )

    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return file_path


def get_file_mime(filename):

    if filename.endswith(".py"):
        return "text/x-python"

    if filename.endswith(".ipynb"):
        return "application/x-ipynb+json"

    return "application/octet-stream"


def load_workspaces():

    workspaces = []

    if not os.path.exists(WORKSPACES_DIR):
        return workspaces

    for workspace_id in os.listdir(WORKSPACES_DIR):

        workspace_path = os.path.join(
            WORKSPACES_DIR,
            workspace_id
        )

        if not os.path.isdir(workspace_path):
            continue

        files = os.listdir(workspace_path)

        for filename in files:

            file_path = os.path.join(
                workspace_path,
                filename
            )

            if os.path.isfile(file_path):

                workspaces.append(
                    {
                        "id": workspace_id,
                        "name": workspace_id,
                        "file": filename,
                        "file_path": file_path
                    }
                )

    return workspaces


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        """
        <h1 style="color:#d71920;">
        🔴 FlexHub
        </h1>
        """,
        unsafe_allow_html=True
    )

    st.caption("Collaborative Data Science Workspace")

    st.markdown("---")

    # ========================================================
    # ACCOUNT SECTION
    # ========================================================

    if st.session_state.logged_in:

        st.markdown("### 👤 Account")

        st.success(
            st.session_state.user_name
        )

        st.caption(
            st.session_state.user_email
        )

        st.caption(
            f"Role: {st.session_state.user_role}"
        )

        if st.button(
            "🚪 Logout",
            use_container_width=True,
            key="sidebar_logout"
        ):

            st.session_state.logged_in = False
            st.session_state.user_name = ""
            st.session_state.user_email = ""
            st.session_state.user_role = "user"
            st.session_state.auth_mode = "login"

            st.rerun()

    else:

        st.markdown("### 🔐 Account")

        st.caption(
            "Login to upload files and create workspaces."
        )

        # ----------------------------------------------------
        # LOGIN / SIGNUP SELECTOR
        # ----------------------------------------------------

        auth_choice = st.radio(
            "Account",
            [
                "Login",
                "Create Account"
            ],
            key="auth_choice"
        )

        # ====================================================
        # LOGIN
        # ====================================================

        if auth_choice == "Login":

            st.markdown("#### Login")

            login_username = st.text_input(
                "Username",
                key="sidebar_login_username"
            )

            login_password = st.text_input(
                "Password",
                type="password",
                key="sidebar_login_password"
            )

            if st.button(
                "🔐 Login",
                use_container_width=True,
                key="sidebar_login_submit"
            ):

                if not login_username or not login_password:

                    st.error(
                        "Please enter username and password."
                    )

                else:

                    try:

                        response = requests.post(
                            f"{API_URL}/login",
                            json={
                                "Username": login_username,
                                "Password": login_password
                            },
                            timeout=10
                        )

                        if response.status_code == 200:

                            data = response.json()

                            st.session_state.logged_in = True

                            st.session_state.user_name = (
                                data.get(
                                    "username",
                                    login_username
                                )
                            )

                            st.session_state.user_email = (
                                data.get(
                                    "email",
                                    ""
                                )
                            )

                            st.session_state.user_role = (
                                data.get(
                                    "role",
                                    "user"
                                )
                            )

                            st.success(
                                "Login successful!"
                            )

                            st.rerun()

                        else:

                            try:
                                detail = response.json().get(
                                    "detail",
                                    "Invalid username or password."
                                )
                            except Exception:
                                detail = (
                                    "Invalid username or password."
                                )

                            st.error(detail)

                    except requests.RequestException:

                        st.error(
                            "Cannot connect to FlexHub API."
                        )

        # ====================================================
        # CREATE ACCOUNT
        # ====================================================

        else:

            st.markdown("#### Create Account")

            signup_username = st.text_input(
                "Username",
                key="sidebar_signup_username"
            )

            signup_email = st.text_input(
                "Email",
                key="sidebar_signup_email"
            )

            signup_password = st.text_input(
                "Password",
                type="password",
                key="sidebar_signup_password"
            )

            st.caption(
                "Password must contain uppercase, lowercase, "
                "number, and special character."
            )

            if st.button(
                "📝 Create Account",
                use_container_width=True,
                key="sidebar_signup_submit"
            ):

                if (
                    not signup_username
                    or not signup_email
                    or not signup_password
                ):

                    st.error(
                        "Please fill in all fields."
                    )

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

                            st.success(
                                "Account created successfully!"
                            )

                            st.info(
                                "Please login using your new account."
                            )

                        else:

                            try:
                                detail = response.json().get(
                                    "detail",
                                    "Could not create account."
                                )
                            except Exception:
                                detail = (
                                    "Could not create account."
                                )

                            st.error(detail)

                    except requests.RequestException:

                        st.error(
                            "Cannot connect to FlexHub API."
                        )

    st.markdown("---")

    # ========================================================
    # NAVIGATION
    # ========================================================

    st.markdown("### Navigation")

    page = st.radio(
        "Go to",
        [
            "🏠 Dashboard",
            "📁 My Workspaces",
            "🤝 Shared With Me",
            "📓 Notebooks",
            "👥 Team",
            "⚙️ Settings"
        ],
        key="navigation"
    )


# ============================================================
# DASHBOARD
# ============================================================

if page == "🏠 Dashboard":

    st.markdown(
        '<div class="main-title">Welcome to FlexHub 🔴</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="subtitle">
        Your collaborative workspace for Data Science,
        Python, and Jupyter Notebooks.
        </div>
        """,
        unsafe_allow_html=True
    )

    # --------------------------------------------------------
    # USER STATUS
    # --------------------------------------------------------

    if st.session_state.logged_in:

        st.success(
            f"Welcome back, {st.session_state.user_name}! "
            "You are logged in."
        )

    else:

        st.info(
            "👋 Welcome! You can explore FlexHub without an account. "
            "Login from the Sidebar when you want to upload files "
            "or create a workspace."
        )

    st.markdown("---")

    # --------------------------------------------------------
    # FEATURES
    # --------------------------------------------------------

    col1, col2, col3 = st.columns(3)

    with col1:

        st.markdown(
            """
            <div class="feature-card">

            ### 📁 Workspaces

            Create organized workspaces for your
            Data Science projects.

            </div>
            """,
            unsafe_allow_html=True
        )

    with col2:

        st.markdown(
            """
            <div class="feature-card">

            ### 📓 Jupyter Notebooks

            Work with Python files and Jupyter
            Notebooks in one place.

            </div>
            """,
            unsafe_allow_html=True
        )

    with col3:

        st.markdown(
            """
            <div class="feature-card">

            ### 👥 Collaboration

            Share and collaborate with your
            team members.

            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("## 🚀 Getting Started")

    col1, col2 = st.columns(2)

    with col1:

        st.markdown(
            """
            ### For new users

            1. Create an account from the Sidebar.
            2. Login.
            3. Create your workspace.
            4. Upload your `.py` or `.ipynb` file.
            """
        )

    with col2:

        st.markdown(
            """
            ### Supported Files

            - 🐍 Python `.py`
            - 📓 Jupyter Notebook `.ipynb`
            - ☁️ Cloud-based workspace
            - 👥 Team collaboration
            """
        )


# ============================================================
# MY WORKSPACES
# ============================================================

elif page == "📁 My Workspaces":

    st.title("📁 My Workspaces")

    if not require_login():
        st.stop()

    st.write(
        f"Welcome, {st.session_state.user_name}."
    )

    st.markdown("---")

    workspaces = load_workspaces()

    if not workspaces:

        st.info(
            "You don't have any workspaces yet."
        )

        st.button(
            "➕ Create Workspace",
            key="workspace_empty_create",
            on_click=go_to_notebooks
        )

    else:

        for workspace in workspaces:

            st.markdown(
                '<div class="workspace-card">',
                unsafe_allow_html=True
            )

            col1, col2, col3 = st.columns(
                [3, 2, 1]
            )

            with col1:

                st.markdown(
                    f"### 📁 {workspace['name']}"
                )

                st.write(
                    f"File: {workspace['file']}"
                )

            with col2:

                st.write(
                    "Owner"
                )

                st.write(
                    st.session_state.user_name
                )

            with col3:

                st.button(
                    "Open",
                    key=f"openworkspace{workspace['id']}",
                    on_click=go_to_notebooks
                )

            st.markdown(
                "</div>",
                unsafe_allow_html=True
            )


# ============================================================
# SHARED WITH ME
# ============================================================

elif page == "🤝 Shared With Me":

    st.title("🤝 Shared With Me")

    if not require_login():
        st.stop()

    st.info(
        "Shared workspaces will appear here."
    )

    st.markdown(
        """
        ### Collaboration

        This section will contain workspaces
        shared with your account by other users.
        """
    )


# ============================================================
# NOTEBOOKS
# ============================================================

elif page == "📓 Notebooks":

    st.title("📓 Notebooks")

    if not require_login():
        st.stop()

    st.write(
        "Create a workspace and upload your Python "
        "file or Jupyter Notebook."
    )

    st.markdown("---")

    # ========================================================
    # CREATE WORKSPACE
    # ========================================================

    st.subheader("➕ Create Workspace")

    workspace_name = st.text_input(
        "Workspace Name",
        placeholder="Example: Machine Learning Project",
        key="workspace_name"
    )

    uploaded_file = st.file_uploader(
        "Upload a Jupyter Notebook or Python file",
        type=["ipynb", "py"],
        key="workspace_file_uploader",
        help="Supported formats: .ipynb and .py"
    )

    if uploaded_file:

        st.success(
            f"📄 Selected file: {uploaded_file.name}"
        )

        file_size = uploaded_file.size

        st.caption(
            f"File size: {file_size / 1024:.2f} KB"
        )

    if st.button(
        "🚀 Create Workspace",
        use_container_width=True,
        key="create_workspace_button"
    ):

        # ----------------------------------------------------
        # LOGIN CHECK
        # ----------------------------------------------------

        if not st.session_state.logged_in:

            st.error(
                "🔐 You must login before creating a workspace."
            )

        elif not workspace_name.strip():

            st.warning(
                "Please enter a workspace name."
            )

        elif not uploaded_file:

            st.warning(
                "Please upload a .py or .ipynb file."
            )

        else:

            # ------------------------------------------------
            # CREATE SAFE WORKSPACE ID
            # ------------------------------------------------

            workspace_id = (
                workspace_name
                .strip()
                .replace(" ", "_")
                .lower()
            )

            # Add username to workspace ID
            workspace_id = (
                f"{st.session_state.user_name}_{workspace_id}"
            )

            # ------------------------------------------------
            # SAVE FILE
            # ------------------------------------------------

            try:

                file_path = save_uploaded_file(
                    uploaded_file,
                    workspace_id
                )

                st.session_state.workspaces.append(
                    {
                        "id": workspace_id,
                        "name": workspace_name,
                        "file": uploaded_file.name,
                        "file_path": file_path
                    }
                )

                st.success(
                    f"Workspace '{workspace_name}' created successfully!"
                )

                st.info(
                    f"File saved: {uploaded_file.name}"
                )

            except Exception as e:

                st.error(
                    f"Could not save the file: {e}"
                )

    st.markdown("---")

    # ========================================================
    # EXISTING FILES
    # ========================================================

    st.subheader("📂 Your Files")

    workspaces = load_workspaces()

    user_workspaces = [
        workspace
        for workspace in workspaces
        if workspace["id"].startswith(
            f"{st.session_state.user_name}_"
        )
    ]

    if not user_workspaces:

        st.info(
            "No files uploaded yet."
        )

    else:

        for workspace in user_workspaces:

            st.markdown(
                f"### 📄 {workspace['file']}"
            )

            st.caption(
                f"Workspace: {workspace['name']}"
            )

            file_path = workspace["file_path"]

            if os.path.exists(file_path):

                with open(
                    file_path,
                    "rb"
                ) as f:

                    file_bytes = f.read()

                st.download_button(
                    label="⬇️ Download File",
                    data=file_bytes,
                    file_name=workspace["file"],
                    mime=get_file_mime(
                        workspace["file"]
                    ),
                    use_container_width=True,
                    key=f"download_{workspace['id']}_{workspace['file']}"
                )

            else:

                st.error(
                    "File not found."
                )

            st.markdown("---")


# ============================================================
# TEAM
# ============================================================

elif page == "👥 Team":

    st.title("👥 Team")

    if not require_login():
        st.stop()

    st.write(
        f"Logged in as **{st.session_state.user_name}**"
    )

    st.markdown("---")

    st.subheader("Team Collaboration")

    st.info(
        "Team members and shared workspace management "
        "will appear here."
    )

    st.markdown(
        """
        ### Planned Features

        - 👤 Add team members
        - 📤 Share workspace
        - 👥 Collaborative notebooks
        - 🔐 Workspace permissions
        - 💬 Team communication
        """
    )


# ============================================================
# SETTINGS
# ============================================================

elif page == "⚙️ Settings":

    st.title("⚙️ Settings")

    if not require_login():
        st.stop()

    st.subheader("Account Information")

    col1, col2 = st.columns(2)

    with col1:

        st.text_input(
            "Username",
            value=st.session_state.user_name,
            disabled=True,
            key="settings_username"
        )

    with col2:

        st.text_input(
            "Email",
            value=st.session_state.user_email,
            disabled=True,
            key="settings_email"
        )

    st.text_input(
        "Role",
        value=st.session_state.user_role,
        disabled=True,
        key="settings_role"
    )

    st.markdown("---")

    st.subheader("FlexHub")

    st.write(
        "FlexHub is a collaborative Data Science "
        "and Jupyter workspace."
    )

    st.write(
        "Version: 1.0.0"
    )