# ArtigianAI Planner v0.2 - backend files

Contenuto:
- backend/app/models.py
- backend/app/schemas.py
- backend/app/crud.py
- backend/app/routes.py
- backend/app/main.py (invariato, incluso per riferimento)
- backend/app/database.py (invariato, incluso per riferimento)
- backend/scripts/migrate_planner_v02.py

Funzioni aggiunte:
- Pianificazione intervento: POST /api/requests/{id}/schedule
- Modifica appuntamento: PUT /api/appointments/{id}
- Calendario filtrabile per giorno/artigiano
- Stima durata basata sui casi completati simili
- Inizio intervento: POST /api/requests/{id}/start
- Completamento con durata reale: POST /api/requests/{id}/complete
- Coordinate richiesta: PUT /api/requests/{id}/location
- Campi per route_order e travel_minutes
- Rimossa la creazione automatica dell'appuntamento "domani + 1 ora" al momento dell'accettazione
- Conservata la gestione WhatsApp/foto; il download media usa settings.uploads_dir

ORDINE CONSIGLIATO DI INSTALLAZIONE

1. Fai un backup/commit dello stato funzionante.
2. Sostituisci i 4 file modificati in backend/app:
   models.py, schemas.py, crud.py, routes.py
3. Copia backend/scripts/migrate_planner_v02.py nel progetto.
4. Dalla cartella backend esegui:
      python -m scripts.migrate_planner_v02
5. Avvia il backend e verifica:
      python -m uvicorn app.main:app --reload
6. Apri /docs e prova gli endpoint planner.
7. Solo dopo il test, commit e push su master.

NOTA
La migrazione usa ADD COLUMN IF NOT EXISTS ed è quindi ri-eseguibile.
Non modifica o cancella richieste, clienti, messaggi, foto o appuntamenti esistenti.
