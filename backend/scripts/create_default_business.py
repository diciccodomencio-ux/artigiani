from app.database import SessionLocal
from app import models


def ensure_default_business():
    db = SessionLocal()
    try:
        b = db.query(models.Business).first()
        if b:
            print('Business exists id=', b.id)
            return b.id
        b = models.Business(business_name='Dev Business', trade_type=models.TradeType.ALTRO, phone='', email='dev@example.com')
        db.add(b)
        db.commit()
        db.refresh(b)
        print('Created Business id=', b.id)
        return b.id
    finally:
        db.close()


if __name__ == '__main__':
    ensure_default_business()
