# ArtigianAI Smart Booking v0.4

Questa patch aggiunge la negoziazione automatica dell'appuntamento via WhatsApp.

## Nuovo flusso

1. L'artigiano accetta la richiesta e sceglie giorno/ora nell'app.
2. Il cliente riceve su WhatsApp una PROPOSTA:
   - CONFERMO
   - NON DISPONIBILE
   - PROPONGO 30/08 15:00
3. Se risponde NON DISPONIBILE:
   - ArtigianAI controlla gli impegni già presenti;
   - usa la durata prevista dell'intervento;
   - applica un buffer di 20 minuti;
   - cerca fino a 3 slot liberi, preferendo giorni diversi;
   - invia le 3 alternative.
4. Il cliente risponde 1, 2 o 3:
   - lo slot viene ricontrollato;
   - se è ancora libero, viene confermato;
   - se nel frattempo è stato occupato, vengono generate nuove alternative.
5. Il cliente può proporre direttamente una data:
   PROPONGO 30/08 15:00
   oppure:
   DOMANI 15:00
   DOPODOMANI 09:30

   Se libera, viene confermata automaticamente.
   Se occupata, il sistema propone 3 alternative.

## Regole beta calendario

- Lunedì-venerdì: 08:00-18:00
- Sabato: 08:30-13:00
- Domenica: chiuso
- Slot su griglia di 30 minuti
- Buffer fra interventi: 20 minuti
- Ricerca alternative: fino a 14 giorni
- Proposte alternative valide 48 ore
- Se è assegnato un tecnico, vengono controllati gli impegni di quel tecnico.
- Se non è assegnato un tecnico, vengono considerati tutti gli appuntamenti del business.

Queste regole sono centralizzate in backend/app/crud.py e potranno diventare
configurabili per singola attività nella versione successiva.

## File da sostituire

backend/app/models.py
backend/app/schemas.py
backend/app/crud.py
backend/app/routes.py
backend/app/storage.py
backend/scripts/migrate_planner_v02.py
frontend/src/App.jsx

NOTA: routes.py e storage.py includono già le modifiche Cloudinary v0.3,
quindi questa patch non riporta il backend al vecchio storage locale.

## Database

Sono aggiunte ad appointments:

proposal_options_json TEXT
proposal_expires_at TIMESTAMP
proposal_round INTEGER DEFAULT 0

Il file migrate_planner_v02.py è stato aggiornato apposta: il tuo Start Command
Render può rimanere invariato:

python -m scripts.migrate_planner_v02 && python -m scripts.seed_staging_user && uvicorn app.main:app --host 0.0.0.0 --port $PORT

Al prossimo deploy vedrai:

Planner migration completed (v0.2 + scheduling v0.4)

## Installazione

Fai prima un backup/commit del progetto.

Poi copia i file del pacchetto nei rispettivi percorsi.

Da PowerShell:

cd C:\Users\ddicicco\artigiani

git add backend/app/models.py backend/app/schemas.py backend/app/crud.py backend/app/routes.py backend/app/storage.py backend/scripts/migrate_planner_v02.py frontend/src/App.jsx

git commit -m "Add automatic WhatsApp appointment negotiation"

git push origin master

## Test consigliato

### Test A - conferma
- Artigiano: invia proposta per 29/08 10:00
- Cliente: CONFERMO
- Atteso: appuntamento CONFIRMATO, customer_confirmed=true
- Nell'app compare "Orario confermato dal cliente"
- Il pulsante Inizia diventa disponibile.

### Test B - cliente non disponibile
- Artigiano: invia proposta
- Cliente: NON DISPONIBILE
- Atteso: WhatsApp mostra fino a 3 alternative.
- Cliente: 2
- Atteso: planner spostato automaticamente sul secondo slot e confermato.

### Test C - proposta cliente libera
Cliente:
PROPONGO 31/08 15:00

Atteso:
"Perfetto, la tua proposta e disponibile. Appuntamento confermato..."

### Test D - proposta cliente occupata
Cliente propone un orario già occupato.

Atteso:
"L'orario che hai proposto non e disponibile"
+ 3 alternative automatiche.

## Frontend

- "Conferma appuntamento" diventa "Invia proposta al cliente".
- Se il cliente non ha ancora confermato, l'app mostra:
  "Proposta inviata · in attesa del cliente".
- "Inizia" è bloccato fino alla conferma del cliente.
- L'auto-refresh già presente continua ad aggiornare il planner dopo le risposte WhatsApp.

## Sicurezza concorrenza

Quando il cliente sceglie 1/2/3, il backend ricontrolla lo slot:
se un altro intervento lo ha occupato nel frattempo non crea una sovrapposizione,
ma genera nuove proposte.

## Prossimo miglioramento

La v0.4 usa calendario + durata + buffer.
La v0.5 può aggiungere posizione geografica/tempo di percorrenza, in modo da
proporre non solo slot liberi ma anche quelli logisticamente migliori.
