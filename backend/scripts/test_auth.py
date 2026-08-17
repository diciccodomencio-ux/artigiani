import urllib.request, json
base='http://127.0.0.1:8000/api'

# register
ud={'business_id':1,'first_name':'Test','last_name':'User','email':'testuser@example.com','password':'secret123'}
req=urllib.request.Request(base+'/auth/register', data=json.dumps(ud).encode('utf-8'), headers={'Content-Type':'application/json'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print('register', r.status, r.read().decode())
except Exception as e:
    print('register error', type(e), e)

# token
data = urllib.parse.urlencode({'username':'testuser@example.com','password':'secret123'}).encode()
req=urllib.request.Request(base+'/auth/token', data=data, headers={'Content-Type':'application/x-www-form-urlencoded'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print('token', r.status, r.read().decode())
except Exception as e:
    print('token error', type(e), e)
