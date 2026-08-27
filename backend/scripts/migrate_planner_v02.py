from sqlalchemy import text

from app.database import engine


STATEMENTS = [
    """
    ALTER TABLE service_requests
    ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION
    """,
    """
    ALTER TABLE service_requests
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION
    """,
    """
    ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS actual_start TIMESTAMP
    """,
    """
    ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS actual_end TIMESTAMP
    """,
    """
    ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS actual_duration_minutes INTEGER
    """,
    """
    ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS route_order INTEGER
    """,
    """
    ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS travel_minutes INTEGER
    """,
    """
    ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS proposal_options_json TEXT
    """,
    """
    ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS proposal_expires_at TIMESTAMP
    """,
    """
    ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS proposal_round INTEGER DEFAULT 0
    """,
]


def run() -> None:
    with engine.begin() as connection:
        for statement in STATEMENTS:
            connection.execute(text(statement))

    print("Planner migration completed (v0.2 + scheduling v0.4)")


if __name__ == "__main__":
    run()
