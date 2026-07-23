"""OneDrive integration via Microsoft Graph (uses app-only token)."""
import httpx
from ..config import get_settings
from .ms_auth import acquire_app_token

settings = get_settings()
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _headers() -> dict:
    return {"Authorization": f"Bearer {acquire_app_token()}"}


def _user_drive_root() -> str:
    """The root drive endpoint for the configured OneDrive user."""
    return f"{GRAPH_BASE}/users/{settings.onedrive_user_email}/drive"


def ensure_folder(folder_path: str) -> dict | None:
    """Create the folder if it doesn't exist. Returns folder info or None on failure.

    folder_path: e.g. "KPI_Tracker" or "KPI_Tracker/Reports/2026-05"
    """
    parts = [p for p in folder_path.split("/") if p]
    if not parts:
        return None

    # Walk down level by level, creating each missing folder
    parent_id = "root"
    last_info = None
    for part in parts:
        if parent_id == "root":
            list_url = f"{_user_drive_root()}/root/children"
            create_url = f"{_user_drive_root()}/root/children"
        else:
            list_url = f"{_user_drive_root()}/items/{parent_id}/children"
            create_url = f"{_user_drive_root()}/items/{parent_id}/children"

        # Try to find existing
        with httpx.Client(timeout=30.0) as client:
            r = client.get(list_url, headers=_headers(), params={"$top": 200})
            r.raise_for_status()
            items = r.json().get("value", [])
            found = next((it for it in items if it.get("name") == part and "folder" in it), None)
            if found:
                parent_id = found["id"]
                last_info = found
                continue

            # Create it
            r = client.post(
                create_url,
                headers=_headers(),
                json={
                    "name": part,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "rename",
                },
            )
            r.raise_for_status()
            info = r.json()
            parent_id = info["id"]
            last_info = info

    return last_info


def upload_file(local_or_bytes, file_name: str, folder_path: str) -> dict:
    """Upload a small file (≤4 MB) to OneDrive at folder_path/file_name.

    Args:
        local_or_bytes: file path str OR bytes
        file_name: target file name
        folder_path: folder path within the user's OneDrive (e.g. "KPI_Tracker/Reports/2026-05")

    Returns: Graph response dict (includes webUrl, id, etc.)
    """
    ensure_folder(folder_path)

    # Read content
    if isinstance(local_or_bytes, (bytes, bytearray)):
        content = bytes(local_or_bytes)
    else:
        with open(local_or_bytes, "rb") as f:
            content = f.read()

    # Encode the path; Graph expects /drive/root:/<path>:/content
    path_encoded = "/".join(folder_path.split("/") + [file_name])
    upload_url = f"{_user_drive_root()}/root:/{path_encoded}:/content"

    with httpx.Client(timeout=120.0) as client:
        r = client.put(upload_url, headers=_headers(), content=content)
        r.raise_for_status()
        return r.json()


def get_share_link(item_id: str, link_type: str = "view") -> str | None:
    """Create an organisation-scoped share link for an item."""
    url = f"{_user_drive_root()}/items/{item_id}/createLink"
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            url,
            headers=_headers(),
            json={"type": link_type, "scope": "organization"},
        )
        if r.status_code >= 400:
            return None
        return r.json().get("link", {}).get("webUrl")


# ============================================================
# Path-based helpers added for the EHS module (Phase 1)
# ============================================================

def _item_by_path_url(path: str) -> str:
    return f"{_user_drive_root()}/root:/{path}"


def upload_to_path(content: bytes, full_path: str, content_type: str = "application/octet-stream") -> dict:
    """Upload bytes to an exact OneDrive path (folders auto-created). ≤4 MB."""
    folder, _, _name = full_path.rpartition("/")
    if folder:
        ensure_folder(folder)
    url = f"{_item_by_path_url(full_path)}:/content"
    with httpx.Client(timeout=60.0) as client:
        r = client.put(url, headers={**_headers(), "Content-Type": content_type}, content=content)
        r.raise_for_status()
        return r.json()


def download_from_path(full_path: str) -> bytes | None:
    """Download a file's bytes by path. Returns None if it doesn't exist."""
    url = f"{_item_by_path_url(full_path)}:/content"
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        r = client.get(url, headers=_headers())
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content


def get_item_by_path(full_path: str) -> dict | None:
    """Item metadata (id, webUrl, ...) by path, or None if missing."""
    with httpx.Client(timeout=30.0) as client:
        r = client.get(_item_by_path_url(full_path), headers=_headers())
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


def delete_by_path(full_path: str) -> bool:
    """Delete a file or folder by path. True if deleted, False if it wasn't there."""
    with httpx.Client(timeout=30.0) as client:
        r = client.delete(_item_by_path_url(full_path), headers=_headers())
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return True


def move_item(src_path: str, dest_folder_path: str, new_name: str | None = None) -> dict | None:
    """Move a file to another folder (same drive). Returns new item or None if src missing."""
    src = get_item_by_path(src_path)
    if not src:
        return None
    dest = ensure_folder(dest_folder_path)
    if not dest:
        raise RuntimeError(f"could not ensure folder {dest_folder_path}")
    body: dict = {"parentReference": {"id": dest["id"]}}
    if new_name:
        body["name"] = new_name
    with httpx.Client(timeout=30.0) as client:
        r = client.patch(
            f"{_user_drive_root()}/items/{src['id']}", headers=_headers(), json=body
        )
        r.raise_for_status()
        return r.json()


def list_children_by_path(full_path: str) -> list[dict]:
    """List items in a folder by path ([] if the folder doesn't exist)."""
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{_item_by_path_url(full_path)}:/children", headers=_headers(), params={"$top": 200})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return r.json().get("value", [])
