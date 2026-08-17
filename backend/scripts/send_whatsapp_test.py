import requests
url = 'https://wildness-pummel-mandatory.ngrok-free.dev/api/whatsapp/webhook'
payload = {'From':'whatsapp:+390000000000','Body':'Prova webhook da ngrok','NumMedia':'0','To':'whatsapp:+14155238886'}
try:
    r = requests.post(url, data=payload, timeout=10)
    print(r.status_code)
    print(r.text)
except Exception as e:
    print('ERROR', e)
