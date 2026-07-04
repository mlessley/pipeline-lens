from sqlmodel import Session

from scie.db import engine, init_db
from scie.store import PipelineRunStore
from scie.synthetic import generate_synthetic_fleet


def main(count: int = 20) -> None:
    init_db()
    fleet = generate_synthetic_fleet(count=count)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        for run in fleet:
            store.upsert(run)
    print(f"Seeded {len(fleet)} synthetic pipeline runs.")


if __name__ == "__main__":
    main()
