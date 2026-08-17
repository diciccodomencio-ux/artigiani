import requests

BASE = 'http://127.0.0.1:8000/api'

# Register a test user (idempotent - may 400 if exists)
reg = {
    'business_id': 1,
    'first_name': 'Upload',
    'last_name': 'Tester',
    'email': 'upload.test@example.com',
    'password': 'secret123'
}
try:
    r = requests.post(BASE + '/auth/register', json=reg, timeout=10)
    print('register', r.status_code, r.text)
except Exception as e:
    print('register err', e)

# Obtain token via form
form = {
    'username': reg['email'],
    'password': reg['password']
}
res = requests.post(BASE + '/auth/token', data=form, timeout=10)
print('token', res.status_code, res.text)
if res.status_code != 200:
    raise SystemExit('token fetch failed')

token = res.json().get('access_token')
headers = {'Authorization': f'Bearer {token}'}

files = {'file': ('test-auth.txt', b'Hello auth upload', 'text/plain')}
resp = requests.post(BASE + '/requests/2/attachments', headers=headers, files=files, data={'caption':'auth prova'}, timeout=10)
print(resp.status_code, resp.text)

resp = requests.get(BASE + '/requests/2/attachments', headers=headers, timeout=10)
print(resp.status_code, resp.text)
