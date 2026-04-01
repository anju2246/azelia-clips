from sqlmodel import create_engine, SQLModel
from packages.core.config import settings

# Usar base de datos nativa local por defecto ("azelia.db")
# para no forzar Postgres localmente si no es necesario.
sqlite_url = "sqlite:///azelia.db"

# Si Supabase / PG URL está definido y queremos usar DB directa
# postgres_url = settings.postgres_url 

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

def init_db():
    from packages.core.db import models
    SQLModel.metadata.create_all(engine)
