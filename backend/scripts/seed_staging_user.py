from app import crud, models, schemas
from app.database import SessionLocal


EMAIL = "dev@example.com"
PASSWORD = "secret123"


def seed_staging_user() -> None:
    db = SessionLocal()
    try:
        business = db.query(models.Business).first()
        if not business:
            business = models.Business(
                business_name="ArtigianAI Staging",
                trade_type=models.TradeType.ALTRO,
                email=EMAIL,
            )
            db.add(business)
            db.commit()
            db.refresh(business)

        user = crud.get_user_by_email(db, EMAIL)
        if not user:
            user = crud.create_user(
                db,
                schemas.UserCreate(
                    business_id=business.id,
                    first_name="Marco",
                    last_name="Artigiano",
                    email=EMAIL,
                    password=PASSWORD,
                ),
            )

        print(f"Staging user ready: {user.email} (id={user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    seed_staging_user()