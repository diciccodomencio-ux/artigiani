import requests

base='http://127.0.0.1:8000/api'
files={'file':('test.txt', b'Hello upload','text/plain')}
resp = requests.post(base + '/requests/2/attachments', files=files, data={'caption':'prova'}, timeout=10)
print(resp.status_code, resp.text)

resp = requests.get(base + '/requests/2/attachments', timeout=10)
print(resp.status_code, resp.text)
