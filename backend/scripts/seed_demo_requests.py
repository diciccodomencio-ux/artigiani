from app.database import SessionLocal
from app import models


def seed_demo_requests():
    db = SessionLocal()

    try:
        # Evita di duplicare i dati ogni volta che esegui lo script
        existing = (
            db.query(models.ServiceRequest)
            .filter(models.ServiceRequest.business_id == 1)
            .first()
        )

        if existing:
            print("Demo service requests already exist.")
            return

        demo_requests = [
            models.ServiceRequest(
                business_id=1,
                description="Perdita d'acqua sotto il lavello della cucina",
                status="pending",
            ),
            models.ServiceRequest(
                business_id=1,
                description="Il salvavita scatta quando viene acceso il forno",
                status="pending",
            ),
            models.ServiceRequest(
                business_id=1,
                description="Il termosifone del soggiorno non scalda",
                status="pending",
            ),
        ]

        db.add_all(demo_requests)
        db.commit()

        for request in demo_requests:
            db.refresh(request)
            print(
                f"Created request ID={request.id}: "
                f"{request.description}"
            )

        print("Demo requests created successfully.")

    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_requests()