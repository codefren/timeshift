import logging

from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy import URL, create_engine
from utils.Config import CONFIG
from SQLModels import *
from .triggers import init_triggers


assert CONFIG.DB_DRIVER in ("ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"), "Driver not supported"

url_obj = URL.create("mssql+pyodbc",
                     username=CONFIG.DB_USERNAME,
                     password=CONFIG.DB_PASSWORD,
                     host=CONFIG.DB_HOST,
                     database=CONFIG.DB_NAME,query={
        "driver": CONFIG.DB_DRIVER,
        "TrustServerCertificate": "yes",
        "trusted_connection":CONFIG.DB_TRUSTED_CONNECTION
    })

engine = create_engine(url_obj.render_as_string(False),
                       pool_pre_ping=True,
                       pool_recycle=3600,
                       connect_args={"connect_timeout": 30}
                       )


def init_db():
    logger = logging.getLogger("init_db")
    logger.info("Creating tables")
    for table in SQLModel.metadata.tables.values():
        logger.info(f"Creating table: {table.name} in main")
    SQLModel.metadata.create_all(engine)
    logger.info(f"Creating triggers")
    init_triggers(engine)


def get_session() -> Session:
    with Session(engine) as session:
        yield session


