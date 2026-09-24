"""Pydantic model for ansible/inventory/group_vars/all/server_apps_defaults.yml.

This is the canonical schema for the deployment defaults (images and published
ports) that were previously hardcoded inside individual Ansible playbooks. Data
directories are not among them: a runbook declares those with guard.path and
passes them to its playbook as extravars, so the directory the guard creates is
the same object as the one the container binds. The model doubles as the JSON
Schema source for VS Code intellisense:

    strata dev schema  # writes .vscode/server_apps_schema.json

The JSON Schema file is referenced from .vscode/settings.json so the YAML is
validated and autocompleted at edit time. Both live under .vscode/, which is
gitignored, so each checkout regenerates the schema with `strata dev schema`.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from strata.core import paths

_PROJECT_ROOT = paths.PROJECT_ROOT
_SCHEMA_PATH = _PROJECT_ROOT / ".vscode" / "server_apps_schema.json"


class BaikalDefaults(BaseModel):
    """Defaults for the Baikal CalDAV/CardDAV server."""

    image: str = "docker.io/ckulka/baikal:nginx"
    port: int = 8080


class JellyfinDefaults(BaseModel):
    """Defaults for the Jellyfin media server."""

    image: str = "docker.io/jellyfin/jellyfin:latest"
    port: int = 8096


class MinioDefaults(BaseModel):
    """Defaults for the MinIO object storage server."""

    image: str = "quay.io/minio/minio:latest"
    port: int = 9000
    console_port: int = 9001


class AnythingLlmDefaults(BaseModel):
    """Defaults for the AnythingLLM document-chat server."""

    image: str = "docker.io/mintplexlabs/anythingllm:1.16"
    port: int = 3001
    site_port: int = 8443
    site_local_port: int = 8088
    site_image: str = "docker.io/nginxinc/nginx-unprivileged:1.30-alpine"


class ServerAppsDefaults(BaseModel):
    """Top-level group_var holding all server-app canonical defaults.

    Loaded automatically by Ansible from
    ``ansible/inventory/group_vars/all/server_apps_defaults.yml``.
    """

    anythingllm: AnythingLlmDefaults
    baikal: BaikalDefaults
    jellyfin: JellyfinDefaults
    minio: MinioDefaults

    @classmethod
    def write_schema(cls) -> Path:
        """Generate the JSON Schema from this model and write it to ``.vscode/``.

        Returns the path written to, so callers can print it or check staleness.
        """
        schema = cls.model_json_schema()
        _SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SCHEMA_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        return _SCHEMA_PATH
