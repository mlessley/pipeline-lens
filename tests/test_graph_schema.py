from graph_fakes import FakeDriver

from scie.graph.schema import CONSTRAINTS, apply_constraints


def test_apply_constraints_runs_every_statement_in_order():
    driver = FakeDriver()

    apply_constraints(driver)

    ran_statements = [call[0] for call in driver.fake_session.calls]
    assert ran_statements == CONSTRAINTS
