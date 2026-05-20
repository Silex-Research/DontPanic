"""Linear PM-tool wrapper: mapping config owns shape; PP adapter owns IO safety."""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate.integrations import pm_tool_sync as sync
from dontpanic_orchestrate.integrations.linear_pp_adapter import LinearPPAdapter
from dontpanic_orchestrate.integrations.pm_tool_mapping import (
    PMToolMappingConfig,
    load_mapping_config,
)
from dontpanic_orchestrate.integrations.pm_tool_models import PMIssue, PMStatus

DEFAULT_CONFIG_PATH: Path = Path.home() / ".dontpanic" / "adapters" / "linear.json"


class LinearPMTool:
    service_name: str = "linear"
    uri_scheme: str = "linear"

    def __init__(self, mapping: PMToolMappingConfig, pp_adapter: LinearPPAdapter) -> None:
        if mapping.service_name != self.service_name:
            raise ValueError(
                f"LinearPMTool requires mapping.service_name == {self.service_name!r}; "
                f"got {mapping.service_name!r}."
            )
        self.mapping = mapping
        self._pp = pp_adapter

    @classmethod
    def from_config_path(
        cls, pp_adapter: LinearPPAdapter, config_path: Path | None = None
    ) -> LinearPMTool:
        path = config_path or DEFAULT_CONFIG_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(mapping=load_mapping_config(payload), pp_adapter=pp_adapter)

    def read_issue(self, uri: str) -> PMIssue:
        issue_id = self._issue_id_from_uri(uri)
        raw = self._pp.call_tool(self.mapping.read_issue_tool, {"issue_id": issue_id})
        return self._translate_issue(raw, uri=uri)

    def push_status(
        self, uri: str, new_status: PMStatus, dry_run: bool = False
    ) -> sync.ExternalSyncRecord:
        issue_id = self._issue_id_from_uri(uri)
        vendor_label = self.mapping.reverse_translate_status(new_status)
        payload = {"issue_id": issue_id, "status": vendor_label}
        if dry_run:
            return sync.make_pending_record(
                ref_uri=uri,
                kind="pm_issue",
                intended_status=new_status,
                payload={"tool": self.mapping.push_status_tool, "arguments": payload},
            )
        try:
            response = self._pp.push_status(self.mapping.push_status_tool, payload)
        except Exception as exc:
            return sync.make_failed_record(
                ref_uri=uri,
                kind="pm_issue",
                intended_status=new_status,
                error=f"{type(exc).__name__}: {exc}",
            )
        return sync.make_pushed_record(
            ref_uri=uri,
            kind="pm_issue",
            intended_status=new_status,
            response=response if isinstance(response, dict) else {"raw": response},
        )

    def _issue_id_from_uri(self, uri: str) -> str:
        prefix = f"{self.mapping.uri_scheme}://issue/"
        if not uri.startswith(prefix):
            raise ValueError(f"URI {uri!r} does not match expected scheme {prefix!r}.")
        return uri[len(prefix) :]

    def _translate_issue(self, raw: dict, uri: str) -> PMIssue:
        vendor_status = self._resolve(raw, self.mapping.field_name_map["PMIssue.status"])
        return PMIssue(
            id=self._resolve(raw, self.mapping.field_name_map["PMIssue.id"]),
            project_id=self._resolve(raw, self.mapping.field_name_map["PMIssue.project_id"]),
            title=self._resolve(raw, self.mapping.field_name_map["PMIssue.title"]),
            status=self.mapping.translate_status(str(vendor_status)),
            uri=uri,
        )

    @staticmethod
    def _resolve(raw: dict, dotted_path: str):
        cursor = raw
        for segment in dotted_path.split("."):
            if isinstance(cursor, dict) and segment in cursor:
                cursor = cursor[segment]
                continue
            raise KeyError(f"Vendor field path {dotted_path!r} not present in MCP response.")
        return cursor
