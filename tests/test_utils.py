from aggregator_service.utils import normalize_job_url


def test_normalize_job_url_removes_tracking_fragment_and_trailing_slash():
    raw = " HTTPS://Jobs.Example.com/roles/42/?utm_source=linkedin&ref=feed#apply "

    normalized = normalize_job_url(raw)

    assert normalized == "https://jobs.example.com/roles/42?ref=feed"
