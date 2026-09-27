# JupyterHub configuration file.
#
# Run with: jupyterhub -f backend/api/jupyterhub_config.py
#
# Ports are deliberately kept off 8000: the FlexHub FastAPI backend listens on
# 8000, so the Hub's public proxy is moved to 8001, and the Hub's own REST API
# stays on its default port 8081 -- which is what HUB_API_URL must point at.
#
# WINDOWS NOTE: JupyterHub's *defaults* are POSIX-only -- PAMAuthenticator needs
# `pamela` (Linux PAM) and LocalProcessSpawner needs the `pwd` module and
# os.setuid. Neither exists on Windows, so this config swaps in DummyAuthenticator
# and a Windows-safe subclass of SimpleLocalProcessSpawner (defined below), both
# of which run as the current user.
# These are DEV-ONLY: DummyAuthenticator accepts any user with a shared password.
# For production, use a real authenticator (OAuth/LDAP) on Linux or in Docker.

import os
import sys
from pathlib import Path

import psutil
from dotenv import load_dotenv
from jupyterhub.spawner import SimpleLocalProcessSpawner
from traitlets.config import get_config

from oauthenticator.azuread import AzureAdOAuthenticator

# Read the same .env the FastAPI backend uses, so HUB_TOKEN matches on both sides.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

c = get_config()  # noqa: F821  -- injected by JupyterHub when it loads this file

# Public proxy: 8001, so it does not collide with the FastAPI backend on 8000.
c.JupyterHub.bind_url = "http://localhost:8001"

# The proxy's control API. This MUST differ from bind_url above: JupyterHub's
# default for it is also 8001, which would make the Hub ask the public listener
# for /api/routes and get a 404 back.
c.ConfigurableHTTPProxy.api_url = "http://localhost:8002"

# The Hub's REST API.
c.JupyterHub.hub_ip = "localhost"
c.JupyterHub.hub_port = 8081

# Windows-compatible auth + spawn (see WINDOWS NOTE above). Dev only.

# Azure authentication
c.JupyterHub.authenticator_class = AzureAdOAuthenticator
c.AzureAdOAuthenticator.tenant_id = os.environ.get("AAD_TENANT_ID")
c.AzureAdOAuthenticator.client_id = os.environ.get("AAD_CLIENT_ID")
c.AzureAdOAuthenticator.client_secret = os.environ.get("AAD_CLIENT_SECRET")
c.AzureAdOAuthenticator.oauth_callback_url = "http://localhost:8001/hub/oauth_callback"

# Allow non-HTTPS state cookies for localhost OAuth testing
c.AzureAdOAuthenticator.legacy_state_cookie = True

# Ensure OAuth state cookies work properly over http on localhost
c.JupyterHub.cookie_options = {
    "SameSite": "Lax",
    "Secure": False,
}
# Automatically allow users who successfully authenticate via Azure
c.Authenticator.allow_all = True

c.LocalAuthenticator.create_system_users = True

c.JupyterHub.default_url = '/hub/home'

class WindowsLocalProcessSpawner(SimpleLocalProcessSpawner):
    """SimpleLocalProcessSpawner that works on Windows.

    The parent passes a POSIX-only preexec_fn to Popen (which raises on Windows)
    and stops servers with signals, including SIGKILL, that Windows lacks. Here
    the home directory is created up front and used as cwd, and stop() kills
    the whole process tree via psutil.
    """

    # Windows system variables the child process needs. JupyterHub only passes
    # an allowlist (env_keep) to single-user servers; without SYSTEMROOT, Python
    # dies at startup with "_Py_HashRandomization_Init: failed to get random numbers".
    windows_env_keep = [
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
        "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    ]

    def get_env(self):
        env = super().get_env()
        for key in self.windows_env_keep:
            if key in os.environ:
                env[key] = os.environ[key]
        # The parent sets SHELL=/bin/bash, which does not exist on Windows.
        env.pop("SHELL", None)
        return env

    def make_preexec_fn(self, name):
        os.makedirs(self.home_dir, exist_ok=True)
        return None

    async def start(self):
        self.popen_kwargs = {**self.popen_kwargs, "cwd": self.home_dir}
        return await super().start()

    async def stop(self, now=False):
        if await self.poll() is not None:
            return
        try:
            proc = psutil.Process(self.pid)
            for child in proc.children(recursive=True):
                child.kill()
            proc.kill()
        except psutil.NoSuchProcess:
            pass
        await self.wait_for_death(self.term_timeout)


c.JupyterHub.spawner_class = WindowsLocalProcessSpawner

# Run the single-user server with this venv's Python directly, so the spawned
# PID is the server itself rather than a .exe launcher wrapping it.
c.Spawner.cmd = [sys.executable, "-m", "jupyterhub.singleuser"]

# Per-user working directories inside the project (default is POSIX /tmp).
c.SimpleLocalProcessSpawner.home_dir_template = str(
    Path(__file__).resolve().parents[2] / "user_homes" / "{username}"
)

# JupyterHub 5+ denies all users unless explicitly allowed.
c.Authenticator.allow_all = True

# The FlexHub backend authenticates as a service. Its token must equal HUB_TOKEN.
c.JupyterHub.services = [
    {
        "name": "flexhub-backend",
        "api_token": os.environ.get("HUB_TOKEN", ""),
    }
]

# Permissions the backend needs to start and stop user servers.
c.JupyterHub.load_roles = [
    {
        "name": "flexhub-backend-role",
        "scopes": ["admin:servers", "admin:users", "list:users"],
        "services": ["flexhub-backend"],
    }
]
