from scie.graph.db import get_driver
from scie.graph.schema import apply_constraints
from scie.graph.synthetic_graph import generate_synthetic_graph


def main(count: int = 15) -> None:
    driver = get_driver()
    apply_constraints(driver)
    generate_synthetic_graph(driver, count=count)
    print(f"Seeded a synthetic graph with {count} repository chains.")


if __name__ == "__main__":
    main()
