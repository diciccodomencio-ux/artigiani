import json
import urllib.request

base='http://127.0.0.1:8000/api'

# create customer
cdata={"business_id":1,"first_name":"Mario","last_name":"Rossi","phone":"+391234567890","email":"mario@example.com","address":"Via Roma 1","city":"Torino","postal_code":"10100"}
req=urllib.request.Request(base+'/customers', data=json.dumps(cdata).encode('utf-8'), headers={'Content-Type':'application/json'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print('create customer status', r.status)
        print(r.read().decode())
except Exception as e:
    print('create customer error', type(e), e)

# list customers
try:
    with urllib.request.urlopen(base+'/customers', timeout=10) as r:
        print('list customers', r.status)
        print(r.read().decode()[:400])
except Exception as e:
    print('list customers error', type(e), e)

# create request
rdata={"business_id":1,"customer_id":None,"source":"WEB_CHAT","category":"PERDITA","description":"Perdita acqua bagno","address":"Via Roma 1","city":"Torino","urgency":"ALTA"}
req=urllib.request.Request(base+'/requests', data=json.dumps(rdata).encode('utf-8'), headers={'Content-Type':'application/json'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print('create request status', r.status)
        print(r.read().decode())
except Exception as e:
    print('create request error', type(e), e)

# list requests
try:
    with urllib.request.urlopen(base+'/requests', timeout=10) as r:
        print('list requests', r.status)
        print(r.read().decode()[:400])
except Exception as e:
    print('list requests error', type(e), e)
