# bot.py

import requests
import pandas as pd
import logging
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine.url import URL
from datetime import datetime
from config import (DATABASE, API_URL, FILTERS, COIN_BLACKLIST, DEV_BLACKLIST,
                    POCKET_UNIVERSE, RUGCHECK, TELEGRAM, BONKBOT, TRADING, SOLANA)
import sys
import time
import os
import json
from telegram import Bot  # python-telegram-bot library

from solana.rpc.api import Client
from solana.publickey import PublicKey
from solana.rpc.core import RPCException

# Setup Logging
logging.basicConfig(filename='bot.log', level=logging.INFO, 
                    format='%(asctime)s %(levelname)s:%(message)s')

# Initialize Telegram Bot
telegram_bot = Bot(token=TELEGRAM['bot_token'])

# Blacklist file path
BLACKLIST_FILE = 'blacklists.json'

def load_blacklists():
    """Load blacklists from a JSON file."""
    try:
        with open(BLACKLIST_FILE, 'r') as f:
            data = json.load(f)
            COIN_BLACKLIST.update(addr.lower() for addr in data.get('coin_blacklist', []))
            DEV_BLACKLIST.update(addr.lower() for addr in data.get('dev_blacklist', []))
            logging.info('Blacklists loaded from file.')
    except FileNotFoundError:
        logging.info('No existing blacklist file found. Starting fresh.')
    except Exception as e:
        logging.error('Error loading blacklists: %s', e)

def save_blacklists():
    """Save blacklists to a JSON file."""
    data = {
        'coin_blacklist': list(COIN_BLACKLIST),
        'dev_blacklist': list(DEV_BLACKLIST)
    }
    try:
        with open(BLACKLIST_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        logging.info('Blacklists saved to file.')
    except Exception as e:
        logging.error('Error saving blacklists: %s', e)

def get_engine():
    """Create a database engine."""
    try:
        engine = create_engine(URL.create(**DATABASE))

        logging.info('Database connection established successfully.')
        return engine
    except Exception as e:
        logging.error('Database connection failed: %s', e)
        sys.exit(1)

def create_tables(engine):
    """Create tables in the database."""
    metadata = MetaData()

    coins = Table('coins', metadata,
                  Column('id', Integer, primary_key=True),
                  Column('token_address', String, unique=True, nullable=False),
                  Column('name', String),
                  Column('symbol', String),
                  Column('price', Float),
                  Column('price_change_1h', Float),
                  Column('price_change_24h', Float),
                  Column('price_change_7d', Float),
                  Column('volume_24h', Float),
                  Column('market_cap', Float),
                  Column('developer', String),
                  Column('timestamp', DateTime, default=datetime.utcnow),
                  Column('event_type', String)
                  )

    try:
        metadata.create_all(engine)
        logging.info('Tables created successfully.')
    except Exception as e:
        logging.error('Error creating tables: %s', e)
        sys.exit(1)

def fetch_data():
    """Fetch data from the Dexscreener API."""
    try:
        response = requests.get(API_URL)
        if response.status_code == 200:
            logging.info('Data fetched successfully from Dexscreener.')
            data = response.json()
            return { 'tokens': data }
        else:
            logging.error('Failed to fetch data: %s', response.status_code)
            return None
    except Exception as e:
        logging.error('Exception occurred while fetching data: %s', e)
        return None

def get_developer_address(token_address):
    try:
        client = Client(SOLANA.get('url'))

        # Validate and create a PublicKey object
        contract_pubkey = PublicKey(token_address)

        # Fetch account information
        response = client.get_account_info(contract_pubkey)

        if not response['result']['value']:
            logging.error(f"Error: No account found for address {contract_address}")
            return None
        
         # Extract owner information
        owner_pubkey = response['result']['value']['owner']

        logging.info(f"Owner of contract {contract_address}: {owner_pubkey}")
        return owner_pubkey
    except Exception as e:
        logging.error('Error fetching developer address from Solscan: %s', e)
        return None

def check_rugcheck(token_address):
    """Verifica a confiabilidade de um token no RugCheck.xyz.

    Args:
        token_address (str): O endereço do token a ser verificado.

    Returns:
        bool: True se o token for considerado bom, False caso contrário.
    """
    # Verifica se o RugCheck está habilitado
    if not RUGCHECK.get('enabled', False):
        logging.info('RugCheck está desabilitado. Assumindo que o token é bom.')
        return True  # Assume que o token é bom se RugCheck estiver desabilitado

    api_url_template = RUGCHECK.get('api_url')
    if not api_url_template:
        logging.warning('URL da API do RugCheck não está configurada.')
        return False  # Retorna False se a URL da API não estiver configurada

    # Formata a URL da API com o endereço do token
    api_url = api_url_template.format(mint=token_address)

    try:
        # Realiza a requisição GET à API do RugCheck
        response = requests.get(api_url, timeout=10)  # Define um timeout para evitar esperas indefinidas
        if response.status_code == 200:
            data = response.json()

            # Extrai o score total do token
            total_score = data.get('score', 0)

            # Verifica se o score total excede o limite definido
            if total_score > 5000:
                logging.info('Token %s possui um score total alto (%d). Considerado como "trash".', token_address, total_score)
                return False

            # Itera sobre os riscos para identificar riscos críticos
            for risco in data.get('risks', []):
                nome = risco.get('name', '').lower()
                nivel = risco.get('level', '').lower()

                # Ignora riscos específicos que podem ser "passados pano"
                if nome in ['copycat token', 'low amount of lp providers']:
                    logging.debug('Risco "%s" identificado, mas será ignorado.', risco.get('name'))
                    continue

                # Considera o token como ruim se houver riscos de nível "danger"
                if nivel == 'danger':
                    logging.info('Token %s possui risco crítico: "%s". Considerado como "trash".', token_address, risco.get('name'))
                    return False

            # Se nenhum risco crítico for encontrado e o score estiver abaixo do limite, considera o token como bom
            logging.info('Token %s passou na verificação do RugCheck. Considerado como bom.', token_address)
            return True
        else:
            logging.error('Erro na API do RugCheck: Código de status %s.', response.status_code)
            return False
    except requests.exceptions.RequestException as e:
        logging.error('Erro ao verificar a API do RugCheck: %s', e)
        return False
    except ValueError as e:
        logging.error('Erro ao processar a resposta JSON da API do RugCheck: %s', e)
        return False

def check_bundled_supply(coin):
    """Check if the coin's supply is bundled using Solscan API."""
    token_address = coin.get('address', '')
    SOLSCAN_HOLDERS_URL = 'https://public-api.solscan.io/token/holders'
    
    params = {
        'tokenAddress': token_address,
        'limit': 100  # Adjust as needed
    }

    try:
        response = requests.get(SOLSCAN_HOLDERS_URL, params=params)
        if response.status_code == 200:
            data = response.json()
            total_supply = float(coin.get('totalSupply', 0))
            if total_supply == 0:
                return False  # Cannot determine without total supply

            # Calculate percentage of supply held by top holders
            top_holders_supply = sum(float(holder['balance']) for holder in data[:5])
            percentage = (top_holders_supply / total_supply) * 100

            if percentage > 50:  # If top 5 holders hold more than 50%
                return True  # Bundled supply detected
        else:
            logging.error('Solscan API error while fetching holders: %s', response.status_code)
            return False
    except Exception as e:
        logging.error('Exception in check_bundled_supply: %s', e)
        return False

    return False

def check_fake_volume(coin):
    """Check if the coin has fake volume using an algorithm and/or Pocket Universe API."""
    # Algorithmic Check
    volume_24h = coin.get('volume', {}).get('h24', 0)
    market_cap = coin.get('fdv', 0)
    price_change_24h = coin.get('priceChange', {}).get('h24', 0)

    try:
        volume_24h = float(volume_24h)
        market_cap = float(market_cap)
        price_change_24h = float(price_change_24h)
    except (ValueError, TypeError):
        return True  # Treat as fake volume if data is invalid

    # Calculate Volume-to-Market Cap Ratio
    if market_cap > 0:
        ratio = volume_24h / market_cap
    else:
        ratio = float('inf')

    max_ratio = FILTERS.get('max_volume_market_cap_ratio', float('inf'))

    if ratio > max_ratio:
        logging.info('Coin %s has high volume-to-market cap ratio (%.2f). Suspected fake volume.', coin.get('address'), ratio)
        return True

    # Check for high volume with minimal price change
    if volume_24h > FILTERS.get('min_volume_24h', 0) and abs(price_change_24h) < 1:
        logging.info('Coin %s has high volume but minimal price change. Suspected fake volume.', coin.get('address'))
        return True

    # Pocket Universe API Check
    if POCKET_UNIVERSE.get('enabled', False):
        is_scam = check_pocket_universe(coin.get('address'))
        if is_scam:
            logging.info('Coin %s identified as scam by Pocket Universe.', coin.get('address'))
            return True

    return False

def check_pocket_universe(token_address):
    """Check if the coin is flagged as a scam using Pocket Universe API."""
    api_key = POCKET_UNIVERSE.get('api_key')
    api_url = POCKET_UNIVERSE.get('api_url')

    if not api_key or not api_url:
        logging.warning('Pocket Universe API key or URL not configured.')
        return False

    headers = {
        'Authorization': f'Bearer {api_key}'
    }

    params = {
        'tokenAddress': token_address
    }

    try:
        response = requests.get(api_url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get('isScam', False):
                return True
        else:
            logging.error('Pocket Universe API error: %s', response.status_code)
            return False
    except Exception as e:
        logging.error('Error checking Pocket Universe API: %s', e)
        return False

    return False

def apply_filters(coin):
    """Apply filters to determine if the coin should be processed."""
    market_cap = coin.get('fdv', 0)
    volume_24h = coin.get('volume', {}).get('h24', 0)
    token_address = coin.get('address', '').lower()

    # Convert values to floats
    try:
        market_cap = float(market_cap)
        volume_24h = float(volume_24h)
    except (ValueError, TypeError):
        return False

    # Check Coin Blacklist
    if token_address in COIN_BLACKLIST:
        logging.info('Coin %s is in the blacklist. Skipping...', token_address)
        return False

    # Check Developer Blacklist
    developer_address = get_developer_address(token_address)
    if developer_address and developer_address.lower() in DEV_BLACKLIST:
        logging.info('Developer %s is blacklisted. Skipping coin %s...', developer_address, token_address)
        return False

    # Check RugCheck
    if not check_rugcheck(token_address):
        logging.info('Coin %s failed RugCheck. Skipping...', token_address)
        return False

    # Check for Bundled Supply
    if check_bundled_supply(coin):
        logging.info('Coin %s has bundled supply. Adding to blacklists and skipping...', token_address)
        # Add to blacklists
        COIN_BLACKLIST.add(token_address)
        if developer_address:
            DEV_BLACKLIST.add(developer_address.lower())
        return False

    # Apply Filters
    if market_cap < FILTERS.get('min_market_cap', 0):
        logging.info('Coin %s does not meet the minimum market cap filter. Skipping...', token_address)
        return False

    if volume_24h < FILTERS.get('min_volume_24h', 0):
        logging.info('Coin %s does not meet the minimum 24h volume filter. Skipping...', token_address)
        return False

    # Check for Fake Volume
    if check_fake_volume(coin):
        logging.info('Coin %s suspected of having fake volume. Skipping...', token_address)
        return False

    return True

def detect_events(coin):
    """Detect events for a given coin."""
    event = None

    price_change_1h = coin.get('priceChange', {}).get('h1', 0)
    price_change_24h = coin.get('priceChange', {}).get('h24', 0)
    market_cap = coin.get('fdv', 0)

    try:
        price_change_1h = float(price_change_1h)
        price_change_24h = float(price_change_24h)
        market_cap = float(market_cap)
    except ValueError:
        price_change_1h = 0
        price_change_24h = 0
        market_cap = 0

    # Rug Pull Detection
    if price_change_1h <= -90:
        event = 'rug_pull'

    # Pump Detection
    elif price_change_24h >= 100:
        event = 'pump'

    # Tier-1 Detection
    elif market_cap >= 1_000_000_000:
        event = 'tier_one'

    # CEX Listing Detection (Placeholder)
    # This requires integration with exchange APIs or scraping their announcements

    return event

def send_telegram_message(message):
    """Send a message via Telegram."""
    try:
        telegram_bot.send_message(chat_id=TELEGRAM['chat_id'], text=message)
        logging.info('Sent Telegram message: %s', message)
    except Exception as e:
        logging.error('Error sending Telegram message: %s', e)

def trade_token(token_address, action):
    """Trade the token using BonkBot via Telegram."""
    if not BONKBOT.get('enabled', False):
        logging.info('BonkBot trading is disabled.')
        return

    bonkbot_username = BONKBOT.get('username', 'BonkBot')
    trade_amount = TRADING.get('trade_amount', 0.1)
    command = ''

    if action == 'buy':
        command = f'/buy {token_address} {trade_amount}'
    elif action == 'sell':
        command = f'/sell {token_address} {trade_amount}'
    else:
        logging.error('Invalid trade action: %s', action)
        return

    try:
        # Send command to BonkBot
        telegram_bot.send_message(chat_id=bonkbot_username, text=command)
        logging.info('Sent trade command to BonkBot: %s', command)

        # Notify user
        send_telegram_message(f'Trade executed: {action.upper()} {trade_amount} of token {token_address}')

    except Exception as e:
        logging.error('Error trading token via BonkBot: %s', e)
        send_telegram_message(f'Error executing trade: {e}')

def process_data(data, engine):
    """Process and store data in the database."""
    if not data or 'tokens' not in data:
        logging.error('No data to process.')
        return

    tokens = data['tokens']
    processed_tokens = []

    for token in tokens:
        token_address = token.get('address', '').lower()

        # Apply Filters and Blacklists
        if not apply_filters(token):
            continue

        developer_address = get_developer_address(token_address)

        coin_data = {
            'token_address': token_address,
            'name': token.get('name'),
            'symbol': token.get('symbol'),
            'price': token.get('price', 0),
            'price_change_1h': token.get('priceChange', {}).get('h1', 0),
            'price_change_24h': token.get('priceChange', {}).get('h24', 0),
            'price_change_7d': token.get('priceChange', {}).get('d7', 0),
            'volume_24h': token.get('volume', {}).get('h24', 0),
            'market_cap': token.get('fdv', 0),
            'developer': developer_address,
            'timestamp': datetime.utcnow(),
            'event_type': None
        }

        # Detect events
        event = detect_events(token)
        if event:
            coin_data['event_type'] = event
            logging.info('Event detected for %s: %s', coin_data['symbol'], event)

            # Execute trade based on event
            if TRADING.get('enabled', False):
                if event == 'pump':
                    trade_token(token_address, 'buy')
                elif event == 'rug_pull':
                    trade_token(token_address, 'sell')
                # Add more conditions as needed

        processed_tokens.append(coin_data)

    if not processed_tokens:
        logging.info('No coins met the criteria after filtering.')
        return

    df = pd.DataFrame(processed_tokens)

    # Store data
    try:
        df.to_sql('coins', engine, if_exists='append', index=False)
        logging.info('Data stored successfully.')
    except IntegrityError as e:
        logging.warning('Integrity error: %s', e)
    except Exception as e:
        logging.error('Error storing data: %s', e)

def main():
    engine = get_engine()
    create_tables(engine)
    load_blacklists()

    try:
        while True:
            data = fetch_data()
            if data:
                process_data(data, engine)
            else:
                logging.error('No data fetched.')
            # Wait for 1 hour before next fetch
            time.sleep(3600)
    except KeyboardInterrupt:
        save_blacklists()
        logging.info('Bot stopped by user.')
        sys.exit(0)
    except Exception as e:
        logging.error('Unexpected error: %s', e)
        save_blacklists()
        sys.exit(1)

if __name__ == '__main__':
    main()
