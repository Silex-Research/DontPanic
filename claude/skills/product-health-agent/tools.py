"""
Custom tool implementations for product-health-agent.

Every tool in this module:
- is READ-ONLY for production projects (glam-ac11e, restaurant-attributes)
- only writes to the insights collection in the workspace project
- keeps all credentials host-side (never shipped into the managed container)
- returns JSON-serializable Python dicts suitable for user.custom_tool_result

Layout convention:
  TOOL_SPECS  — JSON-schema definitions for agents.create (one per tool)
  TOOL_FUNCS  — name → callable mapping (orchestrator dispatch table)
  _impl_*     — actual implementations (one per tool)

The orchestrator imports TOOL_SPECS when creating the agent, and
TOOL_FUNCS when dispatching agent.custom_tool_use events.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any


# ── Firebase / GCP client cache ──────────────────────────────────────

_firestore_clients: dict[str, Any] = {}
_logging_clients: dict[str, Any] = {}
_monitoring_clients: dict[str, Any] = {}


def _firestore(project: str):
    """Get (or create) a google-cloud-firestore client for a project."""
    from google.cloud import firestore  # type: ignore

    if project not in _firestore_clients:
        _firestore_clients[project] = firestore.Client(project=project)
    return _firestore_clients[project]


def _logging(project: str):
    from google.cloud import logging as cloud_logging  # type: ignore

    if project not in _logging_clients:
        _logging_clients[project] = cloud_logging.Client(project=project)
    return _logging_clients[project]


def _monitoring():
    from google.cloud import monitoring_v3  # type: ignore

    if "default" not in _monitoring_clients:
        _monitoring_clients["default"] = monitoring_v3.MetricServiceClient()
    return _monitoring_clients["default"]


def _project_for_app(app: str, config: dict[str, Any]) -> str:
    """Resolve an app name (glam | spindine) to its Firebase project ID."""
    apps_config = config.get("apps", {})
    if app not in apps_config:
        raise ValueError(f"Unknown app '{app}'. Known: {sorted(apps_config.keys())}")
    return apps_config[app]["project_id"]


def _iso_to_dt(s: str) -> datetime:
    """Parse an ISO 8601 string to a timezone-aware datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _safe_serialize(obj: Any) -> Any:
    """Convert Firestore / GCP types to JSON-safe primitives."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    # Firestore DocumentReference, Timestamp, GeoPoint, etc.
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "path"):
        return f"<ref {obj.path}>"
    return str(obj)


# ── Tool: list_functions ─────────────────────────────────────────────

def _impl_list_functions(app: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return Cloud Functions deployed to the app's Firebase project.

    Uses gcloud functions list rather than the Cloud Functions API to avoid
    another client dependency. The agent uses this to know which functions
    to investigate.
    """
    import subprocess

    project = _project_for_app(app, config)
    try:
        result = subprocess.run(
            ["gcloud", "functions", "list", f"--project={project}", "--format=value(name,state)"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return {"error": f"gcloud subprocess failed: {e}"}

    if result.returncode != 0:
        return {"error": result.stderr.strip() or "gcloud returned non-zero"}

    functions = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        name = parts[0] if parts else ""
        state = parts[1] if len(parts) > 1 else "UNKNOWN"
        functions.append({"name": name, "state": state})

    return {
        "app": app,
        "project": project,
        "count": len(functions),
        "functions": functions,
    }


# ── Tool: get_function_errors ────────────────────────────────────────

def _impl_get_function_errors(
    app: str,
    config: dict[str, Any],
    *,
    function_name: str | None = None,
    severity: str = "ERROR",
    since_hours: int = 24,
    limit: int = 50,
) -> dict[str, Any]:
    """Query Cloud Logging for error-level entries from Cloud Functions (gen2).

    Gen2 functions log under resource.type = "cloud_run_revision" with a
    labels.service_name matching the function name (lowercased).
    """
    project = _project_for_app(app, config)
    client = _logging(project)

    filters = [
        'resource.type="cloud_run_revision"',
        f'severity>={severity}',
        f'timestamp>="{(datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()}"',
    ]
    if function_name:
        filters.append(f'resource.labels.service_name="{function_name.lower()}"')

    filter_str = " AND ".join(filters)

    entries = []
    try:
        for entry in client.list_entries(
            filter_=filter_str,
            order_by="timestamp desc",
            page_size=min(limit, 100),
            max_results=limit,
        ):
            payload = entry.payload
            if isinstance(payload, dict):
                msg = payload.get("message") or payload.get("msg") or json.dumps(payload)[:500]
            else:
                msg = str(payload)[:500] if payload else ""

            entries.append({
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "severity": str(entry.severity),
                "function": entry.resource.labels.get("service_name", "unknown") if entry.resource else "unknown",
                "message": msg,
            })
    except Exception as e:
        return {"error": f"Cloud Logging query failed: {e}", "filter": filter_str}

    return {
        "app": app,
        "project": project,
        "filter": filter_str,
        "since_hours": since_hours,
        "count": len(entries),
        "entries": entries,
    }


# ── Tool: search_logs ────────────────────────────────────────────────

def _impl_search_logs(
    app: str,
    config: dict[str, Any],
    *,
    query: str,
    since_hours: int = 24,
    limit: int = 30,
) -> dict[str, Any]:
    """Free-form Cloud Logging search. `query` is a raw Cloud Logging filter fragment.

    Example queries:
      textPayload:"quota exceeded"
      resource.labels.service_name="nearbyrestaurantssimple"
      jsonPayload.userId="abc123" AND severity>=WARNING
    """
    project = _project_for_app(app, config)
    client = _logging(project)

    time_filter = f'timestamp>="{(datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()}"'
    filter_str = f"({query}) AND {time_filter}"

    entries = []
    try:
        for entry in client.list_entries(
            filter_=filter_str,
            order_by="timestamp desc",
            page_size=min(limit, 100),
            max_results=limit,
        ):
            payload = entry.payload
            if isinstance(payload, dict):
                msg = json.dumps(payload)[:600]
            else:
                msg = str(payload)[:600] if payload else ""
            entries.append({
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "severity": str(entry.severity),
                "resource_type": entry.resource.type if entry.resource else None,
                "service_name": entry.resource.labels.get("service_name") if entry.resource else None,
                "message": msg,
            })
    except Exception as e:
        return {"error": f"Cloud Logging query failed: {e}", "filter": filter_str}

    return {
        "app": app,
        "project": project,
        "filter": filter_str,
        "count": len(entries),
        "entries": entries,
    }


# ── Tool: get_function_invocation_stats ──────────────────────────────

def _impl_get_function_invocation_stats(
    app: str,
    config: dict[str, Any],
    *,
    function_name: str | None = None,
    since_hours: int = 24,
) -> dict[str, Any]:
    """Pull invocation counts + execution latency from Cloud Monitoring.

    For gen2 Cloud Functions (Cloud Run under the hood), the relevant metrics are:
      run.googleapis.com/request_count
      run.googleapis.com/request_latencies
    """
    from google.cloud import monitoring_v3  # type: ignore

    project = _project_for_app(app, config)
    client = _monitoring()
    project_name = f"projects/{project}"

    now = int(time.time())
    interval = monitoring_v3.TimeInterval(
        {
            "end_time": {"seconds": now},
            "start_time": {"seconds": now - (since_hours * 3600)},
        }
    )

    filters = ['metric.type="run.googleapis.com/request_count"']
    if function_name:
        filters.append(f'resource.labels.service_name="{function_name.lower()}"')
    filter_str = " AND ".join(filters)

    try:
        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": filter_str,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )
        series = []
        for ts in results:
            total = sum(int(p.value.int64_value) for p in ts.points)
            service = ts.resource.labels.get("service_name", "unknown")
            series.append({
                "service_name": service,
                "total_requests": total,
                "response_code_class": ts.metric.labels.get("response_code_class", "unknown"),
            })
    except Exception as e:
        return {"error": f"Cloud Monitoring query failed: {e}", "filter": filter_str}

    # Aggregate by service
    by_service: dict[str, dict[str, int]] = {}
    for s in series:
        svc = s["service_name"]
        by_service.setdefault(svc, {"total": 0, "2xx": 0, "4xx": 0, "5xx": 0})
        by_service[svc]["total"] += s["total_requests"]
        klass = s["response_code_class"]
        if klass in ("2xx", "4xx", "5xx"):
            by_service[svc][klass] += s["total_requests"]

    summary = [
        {
            "service_name": svc,
            "total": stats["total"],
            "success_2xx": stats["2xx"],
            "client_error_4xx": stats["4xx"],
            "server_error_5xx": stats["5xx"],
            "error_rate": round(
                (stats["4xx"] + stats["5xx"]) / stats["total"], 4
            ) if stats["total"] > 0 else 0,
        }
        for svc, stats in sorted(by_service.items(), key=lambda kv: -kv[1]["total"])
    ]

    return {
        "app": app,
        "project": project,
        "since_hours": since_hours,
        "service_count": len(summary),
        "services": summary,
    }


# ── Tool: get_daily_usage_metrics (Glam-specific collection) ─────────

def _impl_get_daily_usage_metrics(
    app: str,
    config: dict[str, Any],
    *,
    date: str | None = None,
    days: int = 7,
) -> dict[str, Any]:
    """Read Glam's pre-aggregated usage_metrics/{date} documents.

    For apps without this collection (SpinDine), returns a clear hint.
    """
    project = _project_for_app(app, config)
    app_cfg = config["apps"][app]
    collection = app_cfg.get("usage_metrics_collection")
    if not collection:
        return {
            "app": app,
            "available": False,
            "hint": (
                f"No pre-aggregated daily metrics collection configured for {app}. "
                "Use get_function_invocation_stats and get_function_errors instead."
            ),
        }

    db = _firestore(project)

    if date:
        doc = db.collection(collection).document(date).get()
        return {
            "app": app,
            "available": True,
            "collection": collection,
            "date": date,
            "exists": doc.exists,
            "data": _safe_serialize(doc.to_dict()) if doc.exists else None,
        }

    # Last N days
    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    docs = (
        db.collection(collection)
        .where(filter=None)  # placeholder, real filter below
        if False
        else db.collection(collection)
    )
    try:
        snap = list(
            db.collection(collection).order_by("__name__", direction="DESCENDING").limit(days).stream()
        )
    except Exception as e:
        return {"error": f"Firestore query failed: {e}", "collection": collection}

    rows = [
        {"id": d.id, **_safe_serialize(d.to_dict() or {})}
        for d in snap
    ]
    return {
        "app": app,
        "available": True,
        "collection": collection,
        "days": days,
        "count": len(rows),
        "rows": rows,
    }


# ── Tool: get_alerts (Glam-specific collection) ──────────────────────

def _impl_get_alerts(
    app: str,
    config: dict[str, Any],
    *,
    since_days: int = 7,
    limit: int = 30,
) -> dict[str, Any]:
    """Read the app's 'alerts' collection if one exists."""
    project = _project_for_app(app, config)
    app_cfg = config["apps"][app]
    collection = app_cfg.get("alerts_collection")
    if not collection:
        return {"app": app, "available": False, "hint": f"No alerts collection configured for {app}."}

    db = _firestore(project)
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    try:
        # Try to order by timestamp descending; fall back to unordered if the
        # field doesn't exist
        query = db.collection(collection).limit(limit)
        alerts = [{"id": d.id, **_safe_serialize(d.to_dict() or {})} for d in query.stream()]
    except Exception as e:
        return {"error": f"Firestore query failed: {e}", "collection": collection}

    # Filter in Python by any plausible timestamp field
    def _in_window(alert: dict) -> bool:
        for key in ("timestamp", "createdAt", "created_at", "time"):
            v = alert.get(key)
            if v and isinstance(v, str):
                try:
                    return _iso_to_dt(v) >= cutoff
                except ValueError:
                    continue
        return True  # If we can't parse a timestamp, include it

    filtered = [a for a in alerts if _in_window(a)]
    return {
        "app": app,
        "available": True,
        "collection": collection,
        "since_days": since_days,
        "count": len(filtered),
        "alerts": filtered,
    }


# ── Tool: get_trending_stores (Glam-specific) ────────────────────────

def _impl_get_trending_stores(
    app: str,
    config: dict[str, Any],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Read Glam's store_analytics_cache/global trending scores."""
    project = _project_for_app(app, config)
    app_cfg = config["apps"][app]
    collection = app_cfg.get("trending_cache_collection")
    doc_id = app_cfg.get("trending_cache_doc")
    if not (collection and doc_id):
        return {"app": app, "available": False, "hint": f"No trending cache configured for {app}."}

    db = _firestore(project)
    try:
        doc = db.collection(collection).document(doc_id).get()
    except Exception as e:
        return {"error": f"Firestore read failed: {e}"}

    if not doc.exists:
        return {"app": app, "available": False, "hint": f"{collection}/{doc_id} does not exist yet."}

    data = _safe_serialize(doc.to_dict() or {})
    stores = data.get("stores") or data.get("trending") or []
    if isinstance(stores, list):
        stores = stores[:limit]
    return {
        "app": app,
        "available": True,
        "updated_at": data.get("updatedAt") or data.get("updated_at"),
        "top_stores": stores,
    }


# ── Tool: get_firestore_counts ───────────────────────────────────────

def _impl_get_firestore_counts(
    app: str,
    config: dict[str, Any],
    *,
    collections: list[str],
) -> dict[str, Any]:
    """Return document counts for a list of Firestore collections.

    Uses aggregation queries which are cheap. Works for both apps.
    """
    project = _project_for_app(app, config)
    db = _firestore(project)

    counts = {}
    for coll in collections:
        try:
            agg = db.collection(coll).count().get()
            # agg is a list of AggregationResult objects
            count_val = None
            for result in agg:
                for r in result:
                    count_val = r.value
                    break
                if count_val is not None:
                    break
            counts[coll] = count_val
        except Exception as e:
            counts[coll] = {"error": str(e)}

    return {"app": app, "project": project, "counts": counts}


# ── Tool: write_insight ──────────────────────────────────────────────

def _impl_write_insight(
    app: str,
    config: dict[str, Any],
    *,
    severity: str,
    category: str,
    title: str,
    body: str,
    evidence: list[dict[str, Any]] | None = None,
    recommended_actions: list[str] | None = None,
) -> dict[str, Any]:
    """Record an insight in the workspace project.

    Writes to: {workspace_project}/tenants/{tenant}/product_insights/{app}/findings/{auto_id}

    This is the ONLY write operation the agent is authorized to perform, and
    it only touches the workspace project — never production.
    """
    workspace_project = config["workspace"]["project_id"]
    tenant_id = config["workspace"]["tenant_id"]

    if severity not in ("info", "low", "medium", "high", "critical"):
        return {"error": f"Invalid severity '{severity}'. Must be info/low/medium/high/critical."}
    if app not in config["apps"]:
        return {"error": f"Unknown app '{app}'."}

    db = _firestore(workspace_project)
    now = datetime.now(timezone.utc)
    doc_ref = (
        db.collection("tenants").document(tenant_id)
        .collection("product_insights").document(app)
        .collection("findings").document()
    )

    doc = {
        "app": app,
        "severity": severity,
        "category": category,
        "title": title,
        "body": body,
        "evidence": evidence or [],
        "recommended_actions": recommended_actions or [],
        "created_at": now,
        "created_by": "product-health-agent",
        "run_date": now.strftime("%Y-%m-%d"),
    }
    try:
        doc_ref.set(doc)
    except Exception as e:
        return {"error": f"Firestore write failed: {e}"}

    return {
        "written": True,
        "path": doc_ref.path,
        "id": doc_ref.id,
        "severity": severity,
        "title": title,
    }


# ── Tool specs (for agents.create) ───────────────────────────────────

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "custom",
        "name": "list_functions",
        "description": (
            "List all Cloud Functions deployed to a production app's Firebase project. "
            "Use this FIRST to discover which functions exist before investigating specific ones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"], "description": "Which app to query."},
            },
            "required": ["app"],
        },
    },
    {
        "type": "custom",
        "name": "get_function_errors",
        "description": (
            "Query Cloud Logging for error-level log entries from Cloud Functions (gen2). "
            "Returns recent error messages, timestamps, and the function name that logged them. "
            "Use this to investigate operational failures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"]},
                "function_name": {"type": "string", "description": "Optional: filter to one function."},
                "severity": {"type": "string", "enum": ["WARNING", "ERROR", "CRITICAL"], "default": "ERROR"},
                "since_hours": {"type": "integer", "default": 24, "description": "How many hours back."},
                "limit": {"type": "integer", "default": 50, "description": "Max entries to return."},
            },
            "required": ["app"],
        },
    },
    {
        "type": "custom",
        "name": "search_logs",
        "description": (
            "Free-form Cloud Logging search. Pass a raw Cloud Logging filter fragment as `query`. "
            "Example queries: 'textPayload:\"quota exceeded\"', "
            "'resource.labels.service_name=\"nearbyrestaurantssimple\"', "
            "'jsonPayload.userId=\"abc\" AND severity>=WARNING'. The since_hours window is added automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"]},
                "query": {"type": "string", "description": "Cloud Logging filter fragment."},
                "since_hours": {"type": "integer", "default": 24},
                "limit": {"type": "integer", "default": 30},
            },
            "required": ["app", "query"],
        },
    },
    {
        "type": "custom",
        "name": "get_function_invocation_stats",
        "description": (
            "Pull invocation counts and 2xx/4xx/5xx breakdown from Cloud Monitoring for Cloud Functions (gen2). "
            "Use this to find functions with unusually high error rates or traffic patterns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"]},
                "function_name": {"type": "string", "description": "Optional: filter to one function."},
                "since_hours": {"type": "integer", "default": 24},
            },
            "required": ["app"],
        },
    },
    {
        "type": "custom",
        "name": "get_daily_usage_metrics",
        "description": (
            "Read the app's daily usage_metrics Firestore collection (if it exists). "
            "Glam has this — extractions, tryOns, variations, AI cost, error rate, DAU, new users. "
            "SpinDine does not — will return available: false with a hint."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"]},
                "date": {"type": "string", "description": "YYYY-MM-DD. Omit for last N days."},
                "days": {"type": "integer", "default": 7, "description": "Used when date is omitted."},
            },
            "required": ["app"],
        },
    },
    {
        "type": "custom",
        "name": "get_alerts",
        "description": (
            "Read the app's alerts collection (if configured). Returns recent cost/error-rate/anomaly alerts "
            "that the app's own scheduled monitoring raised."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"]},
                "since_days": {"type": "integer", "default": 7},
                "limit": {"type": "integer", "default": 30},
            },
            "required": ["app"],
        },
    },
    {
        "type": "custom",
        "name": "get_trending_stores",
        "description": (
            "Read Glam's trending store engagement scores (store_analytics_cache/global). "
            "Returns the top-N stores by user engagement. Glam-specific."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"]},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["app"],
        },
    },
    {
        "type": "custom",
        "name": "get_firestore_counts",
        "description": (
            "Return document counts for a list of Firestore collections. Works for both apps. "
            "Use this to check collection sizes, detect unusual growth, or validate that data is being written. "
            "Uses cheap aggregation queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"]},
                "collections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of collection paths to count.",
                },
            },
            "required": ["app", "collections"],
        },
    },
    {
        "type": "custom",
        "name": "write_insight",
        "description": (
            "Record a finding as a structured insight document. "
            "This is the ONLY write operation you are authorized to perform. "
            "Severity: info (observation) | low | medium | high (user impact) | critical (data loss / outage). "
            "Always include evidence (refs to logs, metrics, code files) and recommended_actions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["glam", "spindine"]},
                "severity": {"type": "string", "enum": ["info", "low", "medium", "high", "critical"]},
                "category": {
                    "type": "string",
                    "description": "e.g. 'ops_health', 'engagement', 'cost', 'feature_adoption', 'regression'",
                },
                "title": {"type": "string", "description": "Short, scannable — one line."},
                "body": {"type": "string", "description": "Detailed finding with reasoning and context."},
                "evidence": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of evidence refs: {type: 'log'|'metric'|'code'|'doc', ...details}.",
                },
                "recommended_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concrete next steps a human can take.",
                },
            },
            "required": ["app", "severity", "category", "title", "body"],
        },
    },
]


# ── Dispatch table ───────────────────────────────────────────────────

TOOL_FUNCS = {
    "list_functions": _impl_list_functions,
    "get_function_errors": _impl_get_function_errors,
    "search_logs": _impl_search_logs,
    "get_function_invocation_stats": _impl_get_function_invocation_stats,
    "get_daily_usage_metrics": _impl_get_daily_usage_metrics,
    "get_alerts": _impl_get_alerts,
    "get_trending_stores": _impl_get_trending_stores,
    "get_firestore_counts": _impl_get_firestore_counts,
    "write_insight": _impl_write_insight,
}


def dispatch(tool_name: str, tool_input: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Single entry point the orchestrator uses for all custom tool calls."""
    if tool_name not in TOOL_FUNCS:
        return {"error": f"Unknown tool '{tool_name}'"}
    impl = TOOL_FUNCS[tool_name]
    try:
        # Pull `app` out first (it's always positional), pass everything else as kwargs.
        tool_input = dict(tool_input)  # copy to avoid mutating caller's dict
        app = tool_input.pop("app", None)
        if app is None:
            return {"error": f"Missing required parameter 'app' for tool '{tool_name}'"}
        return impl(app, config, **tool_input)  # type: ignore[arg-type]
    except TypeError as e:
        return {"error": f"Tool '{tool_name}' called with bad arguments: {e}"}
    except Exception as e:
        return {"error": f"Tool '{tool_name}' raised an unexpected exception: {type(e).__name__}: {e}"}
