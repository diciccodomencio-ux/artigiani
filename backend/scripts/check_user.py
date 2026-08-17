from app.database import SessionLocal
from app import crud
from app.security import verify_password

email = 'testuser@example.com'

db = SessionLocal()
try:
    u = crud.get_user_by_email(db, email)
    if not u:
        print('user not found')
    else:
        print('id', u.id)
        print('email', u.email)
        print('pw_hash', u.password_hash)
        print('verify secret123 ->', verify_password('secret123', u.password_hash))
finally:
    db.close()
