from scie.models import PipelineStatus
from scie.synthetic import generate_synthetic_fleet


def test_generates_requested_count():
    fleet = generate_synthetic_fleet(count=10, seed=42)
    assert len(fleet) == 10


def test_all_generated_runs_are_flagged_synthetic():
    fleet = generate_synthetic_fleet(count=5, seed=42)
    assert all(run.is_synthetic for run in fleet)


def test_generated_runs_have_a_valid_terminal_status():
    fleet = generate_synthetic_fleet(count=20, seed=42)
    assert all(
        run.overall_status in (PipelineStatus.DEPLOYED, PipelineStatus.DEPLOYED_WITH_FINDINGS)
        for run in fleet
    )


def test_same_seed_is_deterministic():
    first = generate_synthetic_fleet(count=5, seed=7)
    second = generate_synthetic_fleet(count=5, seed=7)
    assert [run.id for run in first] == [run.id for run in second]
