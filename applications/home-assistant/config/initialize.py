import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import shutil
from urllib.request import urlopen
from zipfile import ZipFile

config = Path("/config")
(config / ".storage").mkdir(exist_ok=True)
# HTTP settings moved from YAML to a UI-managed store in Home Assistant 2026.8.
for name, contents in (("automations.yaml", "[]\n"), ("scripts.yaml", "{}\n"), ("scenes.yaml", "[]\n")):
    if not (config / name).exists():
        (config / name).write_text(contents)
if not (config / ".storage/http").exists():
    from homeassistant.components.http.config import (
        HTTP_STORAGE_SCHEMA, STORAGE_VERSION, STORAGE_MINOR_VERSION,
    )
    stable = HTTP_STORAGE_SCHEMA({
        "server_port": 8123,
        "use_x_forwarded_for": True,
        "trusted_proxies": ["10.244.0.0/16"],
        "ip_ban_enabled": True,
        "login_attempts_threshold": 5,
    })
    stable.update(created_at=datetime.now(timezone.utc).isoformat(), error=None, error_message=None)
    (config / ".storage/http").write_text(json.dumps({
        "version": STORAGE_VERSION, "minor_version": STORAGE_MINOR_VERSION, "key": "http",
        "data": {"stable": stable, "pending": None, "yaml_migration_done": True},
    }))

version = "v1.2.1"
digest = "e5badaaacaa63cfd6fe733924a05e76d75058836190398598fb24de57cd47ccd"
component = config / "custom_components/auth_oidc"
marker = component / ".release-sha256"
if not marker.exists() or marker.read_text().strip() != digest:
    url = f"https://github.com/christiaangoossens/hass-oidc-auth/releases/download/{version}/hass-oidc-auth.zip"
    with urlopen(url, timeout=60) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != digest:
        raise ValueError("OIDC component checksum mismatch")
    with ZipFile(BytesIO(archive)) as package:
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in package.namelist()):
            raise ValueError("Invalid OIDC archive path")
        if component.exists():
            shutil.rmtree(component)
        component.mkdir(parents=True)
        package.extractall(component)
    marker.write_text(digest + "\n")
