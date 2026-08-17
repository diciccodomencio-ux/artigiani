import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine, Base
import app.models

print('metadata tables:', list(Base.metadata.tables.keys()))
Base.metadata.create_all(bind=engine)

from sqlalchemy import inspect
insp = inspect(engine)
print('inspected tables:', insp.get_table_names())
