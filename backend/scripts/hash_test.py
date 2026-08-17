from app.security import get_password_hash
p='secret123'
print('len', len(p))
print(get_password_hash(p))
