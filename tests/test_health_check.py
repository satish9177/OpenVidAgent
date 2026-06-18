from backend.app.application.use_cases import HealthCheck


def test_health_check_returns_ok() -> None:
    status = HealthCheck().execute()

    assert status.service == "openvidagent"
    assert status.status == "ok"
