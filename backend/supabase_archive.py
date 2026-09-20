"""Server-only Supabase archive for completed analysis reports and evidence."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class ArchiveError(Exception):
    pass


class SupabaseArchive:
    def __init__(self, project_url, server_key, opener=None, timeout=20):
        self.project_url = project_url.rstrip("/")
        self.server_key = server_key
        self.opener = opener or urlopen
        self.timeout = timeout

    def _request(self, path, method="GET", payload=None, headers=None, binary=False):
        request_headers = {
            "apikey": self.server_key,
            "Accept": "application/json",
        }
        if not self.server_key.startswith("sb_secret_"):
            request_headers["Authorization"] = f"Bearer {self.server_key}"
        request_headers.update(headers or {})
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.project_url}{path}",
            data=payload,
            headers=request_headers,
            method=method,
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                result = response.read()
        except HTTPError as error:
            status = error.code
            error.close()
            raise ArchiveError(f"Supabase returned HTTP {status}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise ArchiveError("Supabase is unavailable") from error
        if binary:
            return result
        if not result:
            return None
        try:
            return json.loads(result.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArchiveError("Supabase returned invalid JSON") from error

    def _table(self, table, params="", method="GET", payload=None):
        suffix = f"?{params}" if params else ""
        return self._request(
            f"/rest/v1/{table}{suffix}",
            method=method,
            payload=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"}
            if method == "POST" else None,
        )

    def get_owner(self, session_id):
        params = urlencode({
            "select": "owner_id",
            "id": f"eq.{session_id}",
            "limit": "1",
        })
        rows = self._table("class_sessions", params) or []
        return rows[0]["owner_id"] if rows else None

    def _catalog_id(self, table, owner_id, name):
        clean_name = str(name or "ไม่ระบุ").strip()[:100] or "ไม่ระบุ"
        params = urlencode({
            "select": "id,name",
            "owner_id": f"eq.{owner_id}",
            "limit": "1000",
        })

        def find_existing():
            rows = self._table(table, params) or []
            return next(
                (row["id"] for row in rows
                 if row["name"].casefold() == clean_name.casefold()),
                None,
            )

        existing_id = find_existing()
        if existing_id is not None:
            return existing_id
        try:
            rows = self._request(
                f"/rest/v1/{table}",
                method="POST",
                payload={"owner_id": owner_id, "name": clean_name},
                headers={"Prefer": "return=representation"},
            )
            return rows[0]["id"]
        except ArchiveError:
            existing_id = find_existing()
            if existing_id is not None:
                return existing_id
            raise

    def archive_report(self, owner_id, report, evidence_store, records=None):
        tracking = report.get("tracking") or {}
        metadata = tracking.get("session") or {}
        session_id = metadata.get("id")
        if not owner_id or not session_id or metadata.get("status") != "completed":
            raise ArchiveError("A completed owned session is required")
        existing_owner = self.get_owner(session_id)
        if existing_owner is not None and existing_owner != owner_id:
            raise ArchiveError("Analysis session belongs to another user")

        uploaded = set()
        for item in tracking.get("evidence", []):
            filename = item.get("filename")
            if not filename or filename in uploaded:
                continue
            file_path = evidence_store.resolve_file(session_id, filename)
            if file_path is None or not os.path.isfile(file_path):
                raise ArchiveError("An evidence image is missing locally")
            with open(file_path, "rb") as image_file:
                image_data = image_file.read()
            object_path = "/".join((owner_id, session_id, filename))
            self._request(
                f"/storage/v1/object/class-evidence/{quote(object_path, safe='/')}",
                method="POST",
                payload=image_data,
                headers={"Content-Type": "image/jpeg", "x-upsert": "true"},
            )
            uploaded.add(filename)

        room_id = self._catalog_id("rooms", owner_id, metadata.get("room_name"))
        course_id = self._catalog_id("courses", owner_id, metadata.get("course_name"))

        session_row = {
            "id": session_id,
            "owner_id": owner_id,
            "name": metadata["name"],
            "room_id": room_id,
            "course_id": course_id,
            "source_type": metadata["source_type"],
            "source_label": metadata.get("source_label"),
            "recording_started_at": metadata["recording_started_at"],
            "ended_at": metadata.get("recording_ended_at"),
            "status": "completed",
        }
        if existing_owner is None:
            self._table("class_sessions", method="POST", payload=session_row)
        else:
            filters = urlencode({
                "id": f"eq.{session_id}",
                "owner_id": f"eq.{owner_id}",
            })
            self._request(
                f"/rest/v1/class_sessions?{filters}",
                method="PATCH",
                payload=session_row,
            )

        records = records or {}
        for table, conflict in (
            ("session_tracks", "session_id,track_id"),
            ("behavior_events", "session_id,track_id,event_index"),
            ("track_time_buckets", "session_id,track_id,bucket_start_seconds"),
            ("evidence_images", "session_id,track_id,evidence_key"),
        ):
            rows = records.get(table, [])
            if table == "evidence_images":
                rows = [
                    {
                        **item,
                        "storage_path": "/".join((
                            owner_id, session_id, item["filename"],
                        )),
                    }
                    for item in rows
                ]
            for index in range(0, len(rows), 100):
                self._table(
                    table,
                    urlencode({"on_conflict": conflict}),
                    "POST",
                    rows[index:index + 100],
                )
        self._table("analysis_jobs", "on_conflict=session_id", "POST", {
            "owner_id": owner_id,
            "session_id": session_id,
            "status": "completed",
            "progress": 100,
            "result_summary": report,
        })

    def list_sessions(self, owner_id):
        params = urlencode({
            "select": "id,name,room_id,course_id,source_type,recording_started_at,ended_at,status,created_at",
            "owner_id": f"eq.{owner_id}",
            "status": "eq.completed",
            "order": "recording_started_at.desc",
            "limit": "100",
        })
        sessions = self._table("class_sessions", params) or []
        if not sessions:
            return []
        job_params = urlencode({
            "select": "session_id",
            "owner_id": f"eq.{owner_id}",
            "status": "eq.completed",
            "limit": "1000",
        })
        completed_ids = {
            item["session_id"]
            for item in self._table("analysis_jobs", job_params) or []
        }
        completed = [item for item in sessions if item["id"] in completed_ids]
        for table, id_field, name_field in (
            ("rooms", "room_id", "room_name"),
            ("courses", "course_id", "course_name"),
        ):
            ids = {item[id_field] for item in completed if item.get(id_field) is not None}
            names = {}
            if ids:
                catalog_params = urlencode({
                    "select": "id,name",
                    "owner_id": f"eq.{owner_id}",
                    "id": f"in.({','.join(str(value) for value in sorted(ids))})",
                })
                names = {
                    row["id"]: row["name"]
                    for row in self._table(table, catalog_params) or []
                }
            for item in completed:
                item[name_field] = names.get(item.get(id_field))
        return completed

    def get_report(self, owner_id, session_id):
        params = urlencode({
            "select": "result_summary",
            "owner_id": f"eq.{owner_id}",
            "session_id": f"eq.{session_id}",
            "status": "eq.completed",
            "limit": "1",
        })
        rows = self._table("analysis_jobs", params) or []
        return rows[0].get("result_summary") if rows else None

    def get_evidence(self, owner_id, session_id, filename):
        if os.path.basename(filename) != filename:
            return None
        report = self.get_report(owner_id, session_id)
        evidence = ((report or {}).get("tracking") or {}).get("evidence", [])
        if not any(item.get("filename") == filename for item in evidence):
            return None
        object_path = "/".join((owner_id, session_id, filename))
        return self._request(
            f"/storage/v1/object/authenticated/class-evidence/"
            f"{quote(object_path, safe='/')}",
            binary=True,
        )
