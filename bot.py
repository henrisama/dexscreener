# bot.py
import base64
import base58
import requests
import pandas as pd
import logging
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine.url import URL
from datetime import datetime
from config import (DATABASE, DEXSCREENER, FILTERS, COIN_BLACKLIST, DEV_BLACKLIST,
                    RUGCHECK, TELEGRAM, BONKBOT, TRADING, SOLANA, WALLET)
import sys
import time
import os
import json
from telegram import Bot  # python-telegram-bot library

from solana.rpc.api import Client
from solana.publickey import PublicKey
from solana.rpc.core import RPCException
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solana.rpc.async_api import AsyncClient
from solana.keypair import Keypair
from solana.rpc.types import TxOpts

import asyncio

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

def fetch_data():
    """Fetch data from the Dexscreener API."""
    try:
        API_URL = DEXSCREENER.get('latest')
        response = requests.get(API_URL)
        if response.status_code == 200:
            logging.info('Data fetched successfully from Dexscreener.')
            data = response.json()
            tokens = [token for token in data if token.get('chainId') == 'solana']
            return {'tokens': tokens}
        else:
            logging.error('Failed to fetch data: %s', response.status_code)
            return None
    except Exception as e:
        logging.error('Exception occurred while fetching data: %s', e)
        return None

# Metaplex Metadata Program ID
METAPLEX_PROGRAM_ID = PublicKey("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")

def find_metadata_pda(mint: PublicKey) -> PublicKey:
    seeds = [
        b"metadata",
        bytes(METAPLEX_PROGRAM_ID),
        bytes(mint)
    ]
    metadata_pda, _ = PublicKey.find_program_address(seeds, METAPLEX_PROGRAM_ID)
    return metadata_pda

def get_developer_address(mint_address):
    try:
        client = Client(SOLANA.get('url'))

        try:
            mint_pubkey = PublicKey(mint_address)
        except ValueError:
            logging.error("Invalid mint address provided.")

        metadata_pda = find_metadata_pda(mint_pubkey)

        # Fetch the account info for the metadata PDA
        response = client.get_account_info(metadata_pda)
        account_info = response.get('result', {}).get('value')

        if not account_info:
            logging.error("Metadata account not found for the given mint address.")

        # The account data is returned as a list where the first element is the base64-encoded data
        data_base64 = account_info.get('data', [])[0]
        if not data_base64:
            logging.error("No data found in the metadata account.")

        # Decode the base64 data
        try:
            decoded_data = base64.b64decode(data_base64)
        except base64.binascii.Error:
            logging.error("Failed to decode account data.")

        # The 'update_authority' is located at bytes 1 to 33 (32 bytes)
        try:
            update_authority_bytes = decoded_data[1:33]
            update_authority_pubkey = PublicKey(update_authority_bytes)
            return str(update_authority_pubkey)
        except Exception as e:
            logging.error(f"Failed to extract update authority: {e}")
    except Exception as e:
        logging.error('Error fetching developer address from Solscan: %s', e)
        return None

def check_rugcheck(token_address):
    # Verifica se o RugCheck está habilitado
    if not RUGCHECK.get('enabled', False):
        logging.info('RugCheck está desabilitado. Assumindo que o token é bom.')
        return True  # Assume que o token é bom se RugCheck estiver desabilitado

    api_url_template = RUGCHECK.get('api_url')
    if not api_url_template:
        logging.warning('URL da API do RugCheck não está configurada.')
        return False  # Retorna False se a URL da API não estiver configurada

    # Formata a URL da API com o endereço do token
    api_url = api_url_template(token_address)

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

def check_bundled_supply(mint_address):
    try:
        client = Client(SOLANA.get('url'))

        try:
            mint_pubkey = PublicKey(mint_address)
        except ValueError:
            logging.error("Invalid mint address provided.")

        # Fetch top holders
        response = client.get_token_largest_accounts(mint_pubkey)

        # Fetch total supply
        supply = client.get_token_supply(mint_pubkey).get('result', {}).get('value', {}).get('amount', 0)

        if response and response.get('result') and supply:
            data = response.get('result').get('value', [])
            total_supply = float(supply)

            if total_supply == 0:
                return False  # Cannot determine without total supply

            # Calculate percentage of supply held by top holders
            top_holders_supply = sum(float(holder['amount']) for holder in data[:5])
            percentage = (top_holders_supply / total_supply) * 100

            if percentage > 50:  # If top 5 holders hold more than 50%
                return True  # Bundled supply detected
        else:
            logging.error('Error while fetching holders or supply:\nResponse: %s\nSupply: %s', response, supply)
            return False
    except Exception as e:
        logging.error('Exception in check_bundled_supply: %s', e)
        return False

    return False

def check_fake_volume(coin):
    """Check if the coin has fake volume using an algorithm"""
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

    return False

def apply_filters(coin):
    """Apply filters to determine if the coin should be processed."""
    market_cap = coin.get('fdv', 0)
    volume_24h = coin.get('volume', {}).get('h24', 0)
    token_address = coin.get('tokenAddress', '')

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
    if check_bundled_supply(token_address):
        logging.info('Coin %s has bundled supply. Adding to blacklists and skipping...', token_address)
        # Add to blacklists
        COIN_BLACKLIST.add(token_address)
        # Add developer to blacklist if is not the pump developer
        if developer_address and developer_address.lower() != 'tslvdd1pwphvjahspsvcxubgwsl3jacvokwakt1eokm':
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

def get_token_data(token_address):
    """Get token data from Dexscreener API."""
    try:
        API_URL = DEXSCREENER.get('pairs')

        response = requests.get(f"{API_URL}/{token_address}")

        if response and response.status_code == 200:
            data = response.json()
            pairs = data.get('pairs', [])

            if pairs:
                oldest_pair = min(pairs, key=lambda x: x.get('pairCreatedAt', float('inf')))
                token_data = {
                    'token_address': token_address,
                    'name': oldest_pair.get('baseToken', {}).get('name'),
                    'symbol': oldest_pair.get('baseToken', {}).get('symbol'),
                    'price': oldest_pair.get('priceUsd', 0),
                    'priceChange': {
                        'h1': oldest_pair.get('priceChange', {}).get('h1', 0),
                        'h24': oldest_pair.get('priceChange', {}).get('h24', 0)
                    },
                    'volume': {
                        'h24': oldest_pair.get('volume', {}).get('h24', 0)
                    },
                    'fdv': oldest_pair.get('fdv', 0)
                }
                return token_data
            else:
                logging.error('No pairs found for token %s.', token_address)
                return None
        else:
            logging.error('Failed to fetch token data: %s', response.status_code)
            return None
    except Exception as e:
        logging.error('Exception occurred while fetching token data: %s', e)
        return None

def send_telegram_message(message):
    """Send a message via Telegram."""
    try:
        telegram_bot.send_message(chat_id=TELEGRAM['chat_id'], text=message)
        logging.info('Sent Telegram message: %s', message)
    except Exception as e:
        logging.error('Error sending Telegram message: %s', e)

async def process_data(data, engine):
    """Process and store data in the database."""
    if not data or 'tokens' not in data:
        logging.error('No data to process.')
        return

    tokens = data['tokens']
    processed_tokens = []

    for token in tokens:
        token_address = token.get('tokenAddress', '')

        # Fetch additional token data
        token_data = get_token_data(token_address)

        token = {**token, **token_data}

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
            'volume_24h': token.get('volume', {}).get('h24', 0),
            'market_cap': token.get('fdv', 0),
            'developer': developer_address,
            'timestamp': datetime.utcnow(),
            'event_type': None,
            'is_held': False
        }

        # Detect events
        event = detect_events(token)
        if event:
            coin_data['event_type'] = event
            logging.info('Event detected for %s: %s', coin_data['symbol'], event)

            # Execute trade based on event
            if TRADING.get('enabled', False):
                if event == 'pump':
                    # Buy token
                    await buy_token(token_address)
                    coin_data['is_held'] = True
                # Add more conditions as needed

        if coin_data['event_type'] == 'pump':
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

def fetch_held_tokens(engine):
    """Fetch tokens that are currently held (bought and not yet sold)."""
    metadata = MetaData(bind=engine)
    coins_table = Table('coins', metadata, autoload_with=engine)

    with engine.connect() as connection:
        query = coins_table.select().where(coins_table.c.is_held == True)
        result = connection.execute(query)
        held_tokens = result.fetchall()

    return held_tokens

async def process_held_tokens(engine):
    """Process held tokens to check for rug_pull events and sell if necessary."""
    held_tokens = fetch_held_tokens(engine)
    if not held_tokens:
        logging.info('No held tokens to process.')
        return

    for token_record in held_tokens:
        token_address = token_record['token_address']
        symbol = token_record['symbol']
        logging.info('Processing held token: %s (%s)', symbol, token_address)

        # Fetch current token data
        token_data = get_token_data(token_address)
        if not token_data:
            logging.error('Failed to fetch data for held token: %s', token_address)
            continue

        # Detect current events
        current_event = detect_events(token_data)

        if current_event == 'rug_pull':
            # Execute sell action
            await sell_token(token_address)

            # Update the database to mark the token as not held
            metadata = MetaData(bind=engine)
            coins_table = Table('coins', metadata, autoload_with=engine)

            update_stmt = coins_table.update().where(
                coins_table.c.token_address == token_address
            ).values(
                is_held=False,
                event_type='rug_pull'
            )

            try:
                with engine.connect() as connection:
                    connection.execute(update_stmt)
                    logging.info('Sold held token: %s (%s) due to rug_pull event.', symbol, token_address)
                    # Notify via Telegram
                    send_telegram_message(f'Sold token {symbol} ({token_address}) due to rug_pull detection.')
            except Exception as e:
                logging.error('Error updating held token status: %s', e)
        else:
            logging.info('No rug_pull event detected for held token: %s (%s)', symbol, token_address)

def load_wallet():
    """Carrega a carteira a partir de um arquivo JSON."""
    try:
        secret_key = WALLET.get('secret_key', '')
        keypair = Keypair.from_secret_key(base58.b58decode(secret_key))

        return keypair
            
    except Exception as e:
        logging.error('Erro ao carregar a carteira: %s', e)

async def get_token_balance(token_mint_address):
    try:
        # Inicializa o cliente da API Solana
        client = Client(SOLANA.get('url'))

        # Carrega a carteira
        wallet = load_wallet()
        token_mint_pubkey = PublicKey(token_mint_address)

        # Obter todas as contas de token associadas à carteira
        response = await client.get_token_accounts_by_owner(wallet.public_key)
        token_accounts = response['result']['value']
        total_balance = 0

        for account in token_accounts:
            account_pubkey = account['pubkey']
            balance_response = await client.get_token_account_balance(account_pubkey)
            balance = balance_response['result']['value']['uiAmount']
            total_balance += balance

        return total_balance
    except Exception as e:
        logging.error('Erro ao obter saldo do token %s: %s', token_mint_address, e)
        return 0


async def buy_token(token_mint_address):
    try:
        # Inicializa o cliente da API Solana
        client = Client(SOLANA.get('url'))

        # Define o valor da compra. Pode ser configurado no arquivo de configuração.
        amount = TRADING.get('trade_amount', 0.005)  # Valor padrão de 0.005 SOL (~1 USD)

        # Carrega a carteira
        wallet = load_wallet()

        # Defina o destinatário como o endereço do DEX ou contrato de swap
        dex_address = PublicKey("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")

        # Crie uma transação de transferência
        transaction = Transaction().add(
            transfer(
                TransferParams(
                    from_pubkey=wallet.public_key,
                    to_pubkey=dex_address,
                    lamports=int(amount * 1e9)  # Convertendo SOL para lamports (1 SOL = 1e9 lamports)
                )
            )
        )

        # Envie a transação
        response = await client.send_transaction(transaction, wallet, opts=TxOpts(preflight_commitment="confirmed"))
        logging.info(f'Compra executada com sucesso. TxID: {response["result"]}')
        send_telegram_message(f'Compra executada: {amount} SOL para {token_mint_address}. TxID: {response["result"]}')
    except Exception as e:
        logging.error('Erro ao comprar token: %s', e)
        send_telegram_message(f'Erro ao comprar token: {e}')

async def sell_token(token_mint_address):
    try:
        # Inicializa o cliente da API Solana
        client = Client(SOLANA.get('url'))

        # Carrega a carteira
        wallet = load_wallet()

        # Obter o saldo total do token
        total_balance = await get_token_balance(token_mint_address)

        if total_balance <= 0:
            logging.info('Nenhum token para vender: %s', token_mint_address)
            return

        # Defina o destinatário como o endereço do DEX ou contrato de swap
        dex_address = PublicKey("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")  # Substitua pelo endereço real

        # Obter a conta de token associada para enviar
        response = await client.get_token_accounts_by_owner(wallet.public_key, mint=PublicKey(token_mint_address))
        token_accounts = response['result']['value']

        if not token_accounts:
            logging.error('Nenhuma conta de token encontrada para %s.', token_mint_address)
            return

        # Usaremos a primeira conta de token para vender
        token_account_pubkey = PublicKey(token_accounts[0]['pubkey'])

        # Obter a conta de token do DEX (deve ser pré-configurada)
        dex_token_account = PublicKey("ENDEREÇO_DA_CONTA_DE_TOKEN_DO_DEX")  # Substitua pelo endereço real

        # Determinar o número de decimais do token (ajuste conforme necessário)
        # Exemplo: USDC tem 6 decimais
        token_decimals = 6  # Substitua pelo número real de decimais do token

        # Converter o saldo para a quantidade de lamports do token
        # Exemplo: Se o token tem 6 decimais, 1 token = 1_000_000 lamports
        lamports = int(total_balance * (10 ** token_decimals))

        # Crie uma transação de transferência de token SPL
        transaction = Transaction().add(
            transfer(
                TransferParams(
                    from_pubkey=token_account_pubkey,
                    to_pubkey=dex_token_account,
                    lamports=lamports  # Convertendo tokens para lamports
                )
            )
        )

        # Envie a transação
        response = await client.send_transaction(transaction, wallet, opts=TxOpts(preflight_commitment="confirmed"))
        tx_id = response["result"]
        logging.info(f'Venda executada com sucesso. TxID: {tx_id}')
        send_telegram_message(f'Venda executada: {total_balance} tokens de {token_mint_address}. TxID: {tx_id}')
    except Exception as e:
        logging.error('Erro ao vender token: %s', e)
        send_telegram_message(f'Erro ao vender token: {e}')

async def main():
    engine = get_engine()
    create_tables(engine)
    load_blacklists()

    try:
        while True:
            data = fetch_data()
            if data:
                await process_data(data, engine)

                # Process held tokens
                await process_held_tokens(engine)
            else:
                logging.error('No data fetched.')
            # Wait for 1 hour before next fetch
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        save_blacklists()
        logging.info('Bot stopped by user.')
        sys.exit(0)
    except Exception as e:
        logging.error('Unexpected error: %s', e)
        save_blacklists()
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
