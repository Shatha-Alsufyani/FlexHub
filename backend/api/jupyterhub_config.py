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

# Read the .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

c = get_config()

# Public proxy and API binding (Changed to 0.0.0.0 for Docker)
c.JupyterHub.bind_url = "http://0.0.0.0:8001"
c.ConfigurableHTTPProxy.api_url = "http://0.0.0.0:8002"
c.JupyterHub.hub_ip = '0.0.0.0'
c.JupyterHub.hub_port = 8081
c.JupyterHub.ip = '0.0.0.0'
c.JupyterHub.port = 8001

# Azure authentication
c.JupyterHub.authenticator_class = AzureAdOAuthenticator
c.AzureAdOAuthenticator.tenant_id = os.environ.get("AAD_TENANT_ID")
c.AzureAdOAuthenticator.client_id = os.environ.get("AAD_CLIENT_ID")
c.AzureAdOAuthenticator.client_secret = os.environ.get("AAD_CLIENT_SECRET")
c.AzureAdOAuthenticator.oauth_callback_url = "http://localhost:8001/hub/oauth_callback"
c.AzureAdOAuthenticator.legacy_state_cookie = True
c.JupyterHub.cookie_options = {"SameSite": "Lax", "Secure": False}

c.Authenticator.allow_all = True
c.LocalAuthenticator.create_system_users = True
c.JupyterHub.default_url = '/hub/home'


class WindowsLocalProcessSpawner(SimpleLocalProcessSpawner):
    windows_env_keep = [
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
        "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    ]

    def get_env(self):
        env = super().get_env()
        for key in self.windows_env_keep:
            if key in os.environ:
                env[key] = os.environ[key]
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


c.Spawner.cmd = [sys.executable, "-m", "jupyterhub.singleuser"]
c.SimpleLocalProcessSpawner.home_dir_template = str(
    Path(__file__).resolve().parents[2] / "user_homes" / "{username}"
)

# Backend service permissions
c.JupyterHub.services = [
    {
        "name": "flexhub-backend",
        "api_token": os.environ.get("HUB_TOKEN", ""),
    }
]

c.JupyterHub.load_roles = [
    {
        "name": "flexhub-backend-role",
        "scopes": ["admin:servers", "admin:users", "list:users"],
        "services": ["flexhub-backend"],
    }
]

# ==========================================
# Routing & Spawning
# ==========================================
c.JupyterHub.spawner_class = 'jupyterhub.spawner.SimpleLocalProcessSpawner'
c.Spawner.default_url = '/lab'
c.JupyterHub.redirect_to_server = True

# THE CRITICAL FIXES FOR SPAWNING:
c.Spawner.args = ['--allow-root']
c.Spawner.ip = '127.0.0.1'
c.Spawner.http_timeout = 120
c.Spawner.start_timeout = 120
