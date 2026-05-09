from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from aggregator_service.ai_client import DailyLimitReached, GroqChatClient, RateLimitError
from aggregator_service.utils import to_json_text


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


@dataclass(frozen=True)
class QueueRow:
    queue_id: int
    profile_id: int
    canonical_job_id: int
    job_title: str | None
    cv_markdown: str


class RelevanceScoringService:
    def __init__(
        self,
        *,
        con_factory,
        client: GroqChatClient,
        system_prompt: str,
        max_request_tokens: int,
        max_response_tokens: int | None,
    ):
        self._con_factory = con_factory
        self._client = client
        self._system_prompt = system_prompt
        self._max_request_tokens = max(200, int(max_request_tokens))
        self._max_response_tokens = max_response_tokens

    def score_run(self, *, run_id: int) -> dict:
        con = self._con_factory()
        try:
            profiles = con.execute("SELECT id, name, cv_markdown FROM profiles").fetchall()
            if not profiles:
                return {"status": "skipped", "reason": "no_profiles"}

            changed = con.execute(
                "SELECT COUNT(*) AS total FROM job_run_changes WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            changed_total = int(changed["total"] if changed else 0)

            if changed_total:
                now = _now_utc_iso()
                for profile in profiles:
                    con.execute(
                        """
                        INSERT INTO profile_job_score_queue(run_id, profile_id, canonical_job_id, queued_at)
                        SELECT ?, ?, canonical_job_id, ?
                        FROM job_run_changes
                        WHERE run_id = ?
                        ON CONFLICT(run_id, profile_id, canonical_job_id)
                        DO NOTHING
                        """,
                        (run_id, int(profile["id"]), now, run_id),
                    )
                con.commit()
        finally:
            con.close()

        return self._drain_queue()

    def _drain_queue(self) -> dict:
        con = self._con_factory()
        try:
            pending = con.execute(
                """
                SELECT q.id AS queue_id,
                       q.profile_id,
                       q.canonical_job_id,
                       c.title AS job_title,
                       p.cv_markdown
                FROM profile_job_score_queue q
                JOIN profiles p ON p.id = q.profile_id
                JOIN jobs_canonical c ON c.id = q.canonical_job_id
                WHERE q.status = 'pending'
                ORDER BY q.profile_id, q.queued_at
                """
            ).fetchall()

            if not pending:
                return {"status": "ok", "queued": 0, "scored": 0, "errors": 0, "pending": 0}

            rows = [
                QueueRow(
                    queue_id=int(row["queue_id"]),
                    profile_id=int(row["profile_id"]),
                    canonical_job_id=int(row["canonical_job_id"]),
                    job_title=row["job_title"],
                    cv_markdown=row["cv_markdown"],
                )
                for row in pending
            ]

            scored_count = 0
            error_count = 0
            daily_limit = False

            for profile_id, profile_rows in _group_by_profile(rows):
                cv_markdown = profile_rows[0].cv_markdown
                remaining = list(profile_rows)
                while remaining:
                    batch, est_tokens = self._build_batch(cv_markdown, remaining)
                    batch_ids = [row.queue_id for row in batch]
                    con.execute(
                        f"UPDATE profile_job_score_queue SET attempts = attempts + 1 WHERE id IN ({','.join(['?'] * len(batch_ids))})",
                        batch_ids,
                    )
                    con.commit()

                    try:
                        user_prompt = self._build_user_prompt(cv_markdown, batch)
                        parsed, total_tokens, _finish, _rate, request_id = self._client.chat_json(
                            con=con,
                            system_prompt=self._system_prompt,
                            user_prompt=user_prompt,
                            est_tokens=est_tokens,
                        )
                    except DailyLimitReached:
                        daily_limit = True
                        break
                    except RateLimitError:
                        return self._summary(con=con, scored=scored_count, errors=error_count, daily_limit=False)
                    except Exception as exc:
                        error_count += len(batch)
                        self._mark_error(con=con, queue_ids=batch_ids, message=f"ai_error: {exc}")
                        remaining = remaining[len(batch) :]
                        continue

                    expected_ids = {row.canonical_job_id: row.queue_id for row in batch}
                    scores, bad_ids = _normalize_scores(parsed, expected_ids)
                    now = _now_utc_iso()

                    if scores:
                        for job_id, queue_id, score in scores:
                            con.execute(
                                """
                                INSERT INTO profile_job_scores(
                                    profile_id, canonical_job_id, run_id, score, scored_at, request_id
                                ) VALUES (?, ?, (SELECT run_id FROM profile_job_score_queue WHERE id = ?), ?, ?, ?)
                                """,
                                (profile_id, job_id, queue_id, score, now, request_id),
                            )
                        con.execute(
                            f"DELETE FROM profile_job_score_queue WHERE id IN ({','.join(['?'] * len(scores))})",
                            [item[1] for item in scores],
                        )
                        con.commit()
                        scored_count += len(scores)

                    if bad_ids:
                        error_count += len(bad_ids)
                        self._mark_error(con=con, queue_ids=bad_ids, message="invalid_ai_output")

                    remaining = remaining[len(batch) :]

                if daily_limit:
                    break

            return self._summary(con=con, scored=scored_count, errors=error_count, daily_limit=daily_limit)
        finally:
            con.close()

    def _build_batch(self, cv_markdown: str, rows: list[QueueRow]) -> tuple[list[QueueRow], int]:
        base_tokens = _estimate_tokens(self._system_prompt) + _estimate_tokens(cv_markdown) + 50
        if self._max_response_tokens:
            base_tokens += int(self._max_response_tokens)

        batch: list[QueueRow] = []
        total_tokens = base_tokens
        for row in rows:
            title = row.job_title or ""
            job_tokens = _estimate_tokens(title) + 6
            if batch and total_tokens + job_tokens > self._max_request_tokens:
                break
            batch.append(row)
            total_tokens += job_tokens

        if not batch:
            batch = [rows[0]]
            total_tokens = base_tokens + _estimate_tokens(rows[0].job_title or "") + 6

        return batch, total_tokens

    def _build_user_prompt(self, cv_markdown: str, batch: Iterable[QueueRow]) -> str:
        job_ids = [row.canonical_job_id for row in batch]
        job_titles = [row.job_title or "" for row in batch]
        payload = {
            "job_ids": job_ids,
            "job_titles": job_titles,
            "cv_markdown": cv_markdown,
        }
        return f"INPUT_JSON:\n{to_json_text(payload)}"

    def _mark_error(self, *, con, queue_ids: list[int], message: str) -> None:
        con.execute(
            f"UPDATE profile_job_score_queue SET status = 'error', last_error = ? WHERE id IN ({','.join(['?'] * len(queue_ids))})",
            [message, *queue_ids],
        )
        con.commit()

    def _summary(self, *, con, scored: int, errors: int, daily_limit: bool) -> dict:
        pending_row = con.execute(
            "SELECT COUNT(*) AS total FROM profile_job_score_queue WHERE status = 'pending'"
        ).fetchone()
        pending_count = int(pending_row["total"] if pending_row else 0)
        return {
            "status": "ok" if not daily_limit else "daily_limit",
            "scored": scored,
            "errors": errors,
            "pending": pending_count,
            "daily_limit_reached": daily_limit,
        }


def _group_by_profile(rows: list[QueueRow]) -> list[tuple[int, list[QueueRow]]]:
    grouped: list[tuple[int, list[QueueRow]]] = []
    current_id: int | None = None
    current_rows: list[QueueRow] = []
    for row in rows:
        if current_id is None or row.profile_id != current_id:
            if current_rows:
                grouped.append((current_id, current_rows))
            current_id = row.profile_id
            current_rows = [row]
        else:
            current_rows.append(row)
    if current_rows:
        grouped.append((current_id, current_rows))
    return grouped


def _normalize_scores(parsed: Any, expected_ids: dict[int, int]) -> tuple[list[tuple[int, int, int]], list[int]]:
    if not isinstance(parsed, list):
        return [], list(expected_ids.values())

    scores: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        job_id = item.get("job_id")
        score = item.get("score")
        try:
            job_id_int = int(job_id)
            score_int = int(score)
        except (TypeError, ValueError):
            continue
        if job_id_int not in expected_ids:
            continue
        if score_int < 0 or score_int > 9:
            continue
        if job_id_int in seen:
            continue
        scores.append((job_id_int, expected_ids[job_id_int], score_int))
        seen.add(job_id_int)

    bad_queue_ids = [queue_id for job_id, queue_id in expected_ids.items() if job_id not in seen]
    return scores, bad_queue_ids
