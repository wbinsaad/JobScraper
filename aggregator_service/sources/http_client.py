import time
from datetime import datetime, timezone

import requests

from aggregator_service.utils import masked_headers, to_json_text, to_sha256


class LoggedHttpClient:
    def __init__(self, timeout_seconds: int, response_excerpt_max_bytes: int):
        self.timeout_seconds = timeout_seconds
        self.response_excerpt_max_bytes = response_excerpt_max_bytes

    def get_json(
        self,
        *,
        con,
        source_name: str,
        run_id: int,
        task_id: str,
        url: str,
        params: dict,
        headers: dict | None = None,
        retry_no: int = 0,
    ) -> tuple[dict, int]:
        request_id = self._log_request(
            con=con,
            run_id=run_id,
            task_id=task_id,
            source_name=source_name,
            method="GET",
            url=url,
            params=params,
            headers=headers,
            retry_no=retry_no,
        )

        start = time.monotonic()
        try:
            response = requests.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            body_text = response.text or ""
            excerpt = body_text[: self.response_excerpt_max_bytes]
            self._log_response(
                con=con,
                request_id=request_id,
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                response_headers=dict(response.headers),
                response_body_excerpt=excerpt,
                body_sha256=to_sha256(body_text),
                success_flag=200 <= response.status_code < 300,
                error_type=None if 200 <= response.status_code < 300 else f"HTTP_{response.status_code}",
                error_message=None if 200 <= response.status_code < 300 else body_text[:200],
            )
            response.raise_for_status()
            return response.json(), request_id
        except requests.Timeout as exc:
            self._log_error(con=con, request_id=request_id, elapsed_ms=int((time.monotonic() - start) * 1000), error_type="timeout", error_message=str(exc))
            raise
        except requests.ConnectionError as exc:
            self._log_error(con=con, request_id=request_id, elapsed_ms=int((time.monotonic() - start) * 1000), error_type="connection", error_message=str(exc))
            raise
        except requests.RequestException as exc:
            self._log_error(con=con, request_id=request_id, elapsed_ms=int((time.monotonic() - start) * 1000), error_type="request", error_message=str(exc))
            raise
        except ValueError as exc:
            self._log_error(con=con, request_id=request_id, elapsed_ms=int((time.monotonic() - start) * 1000), error_type="parse_error", error_message=str(exc))
            raise

    def _log_request(self, *, con, run_id: int, task_id: str, source_name: str, method: str, url: str, params: dict, headers: dict | None, retry_no: int) -> int:
        now = datetime.now(timezone.utc).isoformat()
        masked = masked_headers(headers or {})
        row = con.execute(
            """
            INSERT INTO api_request_log(
                run_id, task_id, source_name, method, url, query_json, headers_json_masked,
                request_body_json, requested_at, timeout_ms, retry_no
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING request_id
            """,
            (
                run_id,
                task_id,
                source_name,
                method,
                url,
                to_json_text(params),
                to_json_text(masked),
                None,
                now,
                self.timeout_seconds * 1000,
                retry_no,
            ),
        ).fetchone()
        con.commit()
        return int(row["request_id"])

    def _log_response(
        self,
        *,
        con,
        request_id: int,
        elapsed_ms: int,
        status_code: int | None,
        response_headers: dict | None,
        response_body_excerpt: str | None,
        body_sha256: str | None,
        success_flag: bool,
        error_type: str | None,
        error_message: str | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        con.execute(
            """
            INSERT INTO api_response_log(
                request_id, responded_at, duration_ms, status_code, response_headers_json,
                response_body_excerpt, body_sha256, success_flag, error_type, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                now,
                elapsed_ms,
                status_code,
                to_json_text(response_headers or {}),
                response_body_excerpt,
                body_sha256,
                1 if success_flag else 0,
                error_type,
                error_message,
            ),
        )
        con.commit()

    def _log_error(self, *, con, request_id: int, elapsed_ms: int, error_type: str, error_message: str) -> None:
        self._log_response(
            con=con,
            request_id=request_id,
            elapsed_ms=elapsed_ms,
            status_code=None,
            response_headers=None,
            response_body_excerpt=None,
            body_sha256=None,
            success_flag=False,
            error_type=error_type,
            error_message=error_message[:300],
        )
