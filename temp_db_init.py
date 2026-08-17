from sqlalchemy import inspect
from app.database import engine, Base
from app import models

insp = inspect(engine)
print('before', insp.get_table_names())
Base.metadata.create_all(engine)
insp = inspect(engine)
print('after', insp.get_table_names())
