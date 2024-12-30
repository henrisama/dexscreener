import sys
import logging
from datetime import datetime

from config import DATABASE

from sqlalchemy.engine.url import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime, Boolean

def get_engine():
    try:
        engine = create_engine(URL.create(**DATABASE))

        logging.info('Database connection established successfully.')
        return engine
    except Exception as e:
        logging.error('Database connection failed: %s', e)
        sys.exit(1)

def create_tables(engine):
    metadata = MetaData()

    coins = Table('coins', metadata,
                  Column('id', Integer, primary_key=True),
                  Column('token_address', String, unique=True, nullable=False),
                  Column('name', String),
                  Column('symbol', String),
                  Column('price', Float),
                  Column('price_change_1h', Float),
                  Column('price_change_24h', Float),
                  Column('volume_24h', Float),
                  Column('market_cap', Float),
                  Column('developer', String),
                  Column('timestamp', DateTime, default=datetime.utcnow),
                  Column('event_type', String),
                  Column('is_held', Boolean, default=False)
                  )

    try:
        metadata.create_all(engine)
        logging.info('Tables created successfully.')
    except Exception as e:
        logging.error('Error creating tables: %s', e)
        sys.exit(1)

def fetch_held_tokens(engine):
    metadata = MetaData(bind=engine)
    coins_table = Table('coins', metadata, autoload_with=engine)

    with engine.connect() as connection:
        query = coins_table.select().where(coins_table.c.is_held == True)
        result = connection.execute(query)
        held_tokens = result.fetchall()

    return held_tokens