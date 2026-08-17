from app.security import _pbkdf2_hash, verify_password
import base64, hashlib

pw='secret123'
h=_pbkdf2_hash(pw)
print('hash', h)
parts=h.split('$')
print('parts len', len(parts))
iterations=int(parts[1])
salt=base64.b64decode(parts[2])
expected=base64.b64decode(parts[3])
print('iterations', iterations)
print('salt bytes', len(salt), salt.hex())
print('expected dk', len(expected), expected.hex())
dk=hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, iterations)
print('computed dk', len(dk), dk.hex())
print('equal', dk==expected)
print('verify_password', verify_password(pw, h))
