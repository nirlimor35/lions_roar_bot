import logging
import time

from flask import Request, Response, jsonify
from functions_framework import http
from google.api_core import exceptions as gcp_exceptions
from google.auth import exceptions as google_auth_exceptions
from google.cloud.compute_v1 import InstancesClient, ZoneOperationsClient
from google.cloud.compute_v1.types import Instance, Operation

logger = logging.getLogger(__name__)

GCP_PROJECT_ID = "lions-roar-2501"
GCP_ZONE = "us-central1-a"
GCP_INSTANCE_NAME = "lions-roar"
EXPECTED_INFO = "lions-25011987-roar"
OPERATION_POLL_INTERVAL_SEC = 3.0
OPERATION_MAX_WAIT_SEC = 300


@http
def instance_handle(request: Request) -> tuple[Response, int]:
    raw_action = request.args.get("action")
    raw_info = request.args.get("info")
    if not _nonempty_query_value(raw_info):
        return (
            jsonify(
                {
                    "error": "missing required query parameter"
                },
            ),
            400,
        )
    if not _nonempty_query_value(raw_action):
        return (
            jsonify(
                {
                    "error": "missing required query parameter"
                },
            ),
            400,
        )

    secret = str(raw_info).strip().lower()
    action = str(raw_action).strip().lower()
    if secret != EXPECTED_INFO:
        return jsonify({"error": "invalid info"}), 401
    if action not in ("start", "stop"):
        return (
            jsonify(
                {
                    "error": "invalid action",
                    "hint": "action must be start or stop",
                },
            ),
            400,
        )

    try:
        instances = InstancesClient()
        zone_ops = ZoneOperationsClient()
        instance = _fetch_instance(instances)
        skip_payload = _early_exit_if_already_aligned(instance, action)

        if skip_payload is not None:
            return jsonify(skip_payload), 200

        op = _run_instance_action(instances, action)
        _wait_zone_operation_until_done(zone_ops, op.name)

    except gcp_exceptions.NotFound as exc:
        logger.warning("instance or resource not found: %s", exc)
        return jsonify({"error": "not found", "detail": str(exc)}), 404

    except gcp_exceptions.GoogleAPICallError as exc:
        logger.warning("compute API error: %s", exc)
        return jsonify({"error": "compute API error", "detail": str(exc)}), 502

    except (
        google_auth_exceptions.DefaultCredentialsError,
        google_auth_exceptions.RefreshError,
    ) as exc:
        logger.warning("google auth error: %s", exc)
        return jsonify({"error": "google auth failed", "detail": str(exc)}), 503

    except RuntimeError as exc:
        logger.warning("operation failed: %s", exc)
        return jsonify({"error": "operation failed", "detail": str(exc)}), 502

    except TimeoutError as exc:
        logger.warning("operation wait timed out: %s", exc)
        return jsonify({"error": "timeout", "detail": str(exc)}), 504

    except Exception as exc:
        logger.exception("unhandled error in instance_handle")
        return jsonify({"error": "internal error", "detail": str(exc)}), 500

    payload = _base_payload(action)
    payload["changed"] = True
    payload["message"] = f"instance {action} requested and operation completed"
    return jsonify(payload), 200


def _fetch_instance(client: InstancesClient) -> Instance:
    return client.get(
        project=GCP_PROJECT_ID,
        zone=GCP_ZONE,
        instance=GCP_INSTANCE_NAME,
    )


def _early_exit_if_already_aligned(instance: Instance, action: str) -> dict | None:
    status = _parse_instance_status(instance.status)
    name = status.name
    base = _base_payload(action)
    base["instance_status"] = name
    base["changed"] = False

    if action == "start":
        if status == Instance.Status.RUNNING:
            base["message"] = "instance already running"
            return base
        if status in (Instance.Status.STOPPED, Instance.Status.TERMINATED):
            return None
        if status == Instance.Status.STOPPING:
            base["message"] = "instance is stopping; wait until stopped before starting"
            return base
        base["message"] = f"instance status is {name}; cannot start from this state"
        return base

    if status == Instance.Status.RUNNING:
        return None
    if status in (Instance.Status.STOPPED, Instance.Status.TERMINATED):
        base["message"] = "instance already stopped"
        return base
    if status == Instance.Status.STOPPING:
        base["message"] = "instance is already stopping"
        return base
    base["message"] = f"instance status is {name}; stop not applicable"
    return base


def _base_payload(action: str) -> dict:
    return {
        "status": "ok",
        "action": action,
        "project": GCP_PROJECT_ID,
        "zone": GCP_ZONE,
        "instance": GCP_INSTANCE_NAME,
    }


def _run_instance_action(client: InstancesClient, action: str) -> Operation:
    if action == "start":
        return client.start(
            project=GCP_PROJECT_ID,
            zone=GCP_ZONE,
            instance=GCP_INSTANCE_NAME,
        )
    return client.stop(
        project=GCP_PROJECT_ID,
        zone=GCP_ZONE,
        instance=GCP_INSTANCE_NAME,
    )


def _wait_zone_operation_until_done(
    zone_ops: ZoneOperationsClient, operation_name: str
) -> None:
    deadline = time.monotonic() + OPERATION_MAX_WAIT_SEC
    while time.monotonic() < deadline:
        current = zone_ops.get(
            project=GCP_PROJECT_ID,
            zone=GCP_ZONE,
            operation=operation_name,
        )
        if current.status == Operation.Status.DONE:
            op_err = current.error
            if op_err and op_err.errors:
                msgs = [e.message for e in op_err.errors if e.message]
                raise RuntimeError(
                    "; ".join(msgs) if msgs else "operation failed",
                )
            return
        time.sleep(OPERATION_POLL_INTERVAL_SEC)
    raise TimeoutError(
        f"operation {operation_name} not DONE within {OPERATION_MAX_WAIT_SEC}s",
    )


def _nonempty_query_value(value: object | None) -> bool:
    if value is None:
        return False
    return str(value).strip() != ""


def _parse_instance_status(raw: object) -> Instance.Status:
    if isinstance(raw, Instance.Status):
        return raw
    if isinstance(raw, str):
        return Instance.Status[raw]
    if isinstance(raw, int):
        return Instance.Status(raw)
    raise TypeError(f"unexpected instance.status type: {type(raw).__name__}")
