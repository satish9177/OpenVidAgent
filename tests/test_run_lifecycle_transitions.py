import pytest

from backend.app.domain import InvalidRunTransitionError, Run, RunStatus


def test_run_can_follow_happy_path_lifecycle() -> None:
    run = Run(run_id="run-1", prompt="make a short product video")

    run = run.mark_script_ready("draft script")
    assert run.status is RunStatus.SCRIPT_READY
    assert run.script == "draft script"

    run = run.approve_script("approved script")
    assert run.status is RunStatus.SCRIPT_APPROVED
    assert run.approved_script == "approved script"

    run = run.mark_scenes_ready()
    assert run.status is RunStatus.SCENES_READY

    run = run.approve_scenes()
    assert run.status is RunStatus.SCENES_APPROVED

    run = run.mark_rendered()
    assert run.status is RunStatus.RENDERED


def test_run_can_fail_from_active_statuses() -> None:
    active_runs = [
        Run(run_id="created", prompt="prompt"),
        Run(run_id="script-ready", prompt="prompt").mark_script_ready("script"),
        Run(run_id="script-approved", prompt="prompt")
        .mark_script_ready("script")
        .approve_script(),
        Run(run_id="scenes-ready", prompt="prompt")
        .mark_script_ready("script")
        .approve_script()
        .mark_scenes_ready(),
        Run(run_id="scenes-approved", prompt="prompt")
        .mark_script_ready("script")
        .approve_script()
        .mark_scenes_ready()
        .approve_scenes(),
    ]

    for run in active_runs:
        failed = run.mark_failed("provider unavailable")
        assert failed.status is RunStatus.FAILED
        assert failed.failure_reason == "provider unavailable"


@pytest.mark.parametrize(
    ("run", "transition"),
    [
        (Run(run_id="run-1", prompt="prompt"), lambda run: run.approve_script()),
        (
            Run(run_id="run-2", prompt="prompt").mark_script_ready("script"),
            lambda run: run.mark_scenes_ready(),
        ),
        (
            Run(run_id="run-3", prompt="prompt")
            .mark_script_ready("script")
            .approve_script()
            .mark_scenes_ready(),
            lambda run: run.mark_rendered(),
        ),
        (
            Run(run_id="run-4", prompt="prompt")
            .mark_script_ready("script")
            .approve_script()
            .mark_scenes_ready()
            .approve_scenes()
            .mark_rendered(),
            lambda run: run.mark_failed("too late"),
        ),
        (
            Run(run_id="run-5", prompt="prompt").mark_failed("stopped"),
            lambda run: run.mark_script_ready("script"),
        ),
    ],
)
def test_invalid_run_transitions_fail_clearly(run: Run, transition: object) -> None:
    with pytest.raises(InvalidRunTransitionError, match="Cannot transition run"):
        transition(run)
