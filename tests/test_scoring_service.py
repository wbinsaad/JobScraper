from aggregator_service.services.scoring_service import _normalize_scores


def test_normalize_scores_accepts_only_expected_unique_scores_in_range():
    expected_queue_ids = {101: 11, 102: 12}
    ai_output = [
        {"job_id": 101, "score": "9"},
        {"job_id": 101, "score": 3},
        {"job_id": 999, "score": 8},
        {"job_id": 102, "score": 10},
        {"job_id": "not-an-id", "score": 5},
    ]

    scores, bad_queue_ids = _normalize_scores(ai_output, expected_queue_ids)

    assert scores == [(101, 11, 9)]
    assert bad_queue_ids == [12]
