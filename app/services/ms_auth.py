"""Microsoft 365 OAuth via MSAL (server-side flow)."""
import msal
from urllib.parse import urlencode
from ..config import get_settings

settings = get_settings()

# Scopes:
# - openid, profile, email, User.Read for SSO identity
# - Files.ReadWrite.All so the service account (info@metfraa.com) can write to OneDrive
LOGIN_SCOPES = ["User.Read"]

# Authority — using "common" to support any Microsoft account, but you can lock to your tenant for tighter security:
def _authority() -> str:
    if settings.ms_tenant_id:
        return f"https://login.microsoftonline.com/{settings.ms_tenant_id}"
    return "https://login.microsoftonline.com/common"


def _msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        client_credential=settings.ms_client_secret,
        authority=_authority(),
    )


def build_login_url(state: str) -> str:
    """Get the Microsoft login URL the user should be redirected to."""
    app = _msal_app()
    return app.get_authorization_request_url(
        scopes=LOGIN_SCOPES,
        state=state,
        redirect_uri=settings.ms_redirect_uri,
        prompt="select_account",
    )


def acquire_token(code: str) -> dict:
    """Exchange the auth code for a token + user info."""
    app = _msal_app()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=LOGIN_SCOPES,
        redirect_uri=settings.ms_redirect_uri,
    )
    if "error" in result:
        raise RuntimeError(f"MS auth failed: {result.get('error_description')}")
    return result


def get_user_email(token_result: dict) -> str | None:
    """Extract the user's email from the ID token claims."""
    claims = token_result.get("id_token_claims", {})
    return (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
    )


def get_user_name(token_result: dict) -> str | None:
    claims = token_result.get("id_token_claims", {})
    return claims.get("name")


# ------- App-only token (for OneDrive access using service account) -------

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


def acquire_app_token() -> str:
    """Get an app-only token to call Microsoft Graph (for OneDrive ops).

    Uses the client_credentials flow. Requires Azure AD app to have:
    - Application permission: Files.ReadWrite.All (admin consented)
    - Application permission: User.Read.All (admin consented, optional)
    """
    app = msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        client_credential=settings.ms_client_secret,
        authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
    )
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"Could not acquire app token: {result.get('error_description')}")
    return result["access_token"]
