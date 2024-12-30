# bot.py
import requests
import pandas as pd
import logging

from datetime import datetime

from config import (DATABASE, DEXSCREENER, FILTERS, COIN_BLACKLIST, DEV_BLACKLIST, TRADING)

import sys
import time
import asyncio

logging.basicConfig(filename='bot.log', level=logging.INFO, 
                    format='%(asctime)s %(levelname)s:%(message)s')

from blockchain import get_token_balance, buy_token
from filters import check_rugcheck, check_bundled_supply, check_fake_volume
from utils import send_telegram_message, get_developer_address, load_blacklists, save_blacklists, get_token_data

def fetch_data():
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


def apply_filters(coin):
    market_cap = coin.get('fdv', 0)
    volume_24h = coin.get('volume', {}).get('h24', 0)
    token_address = coin.get('tokenAddress', '')

    try:
        market_cap = float(market_cap)
        volume_24h = float(volume_24h)
    except (ValueError, TypeError):
        return False

    if token_address in COIN_BLACKLIST:
        logging.info('Coin %s is in the blacklist. Skipping...', token_address)
        return False

    developer_address = get_developer_address(token_address)
    if developer_address and developer_address.lower() in DEV_BLACKLIST:
        logging.info('Developer %s is blacklisted. Skipping coin %s...', developer_address, token_address)
        return False

    if not check_rugcheck(token_address):
        logging.info('Coin %s failed RugCheck. Skipping...', token_address)
        return False

    if check_bundled_supply(token_address):
        logging.info('Coin %s has bundled supply. Adding to blacklists and skipping...', token_address)
        COIN_BLACKLIST.add(token_address)
        # Add developer to blacklist if is not the pump developer
        if developer_address and developer_address.lower() != 'tslvdd1pwphvjahspsvcxubgwsl3jacvokwakt1eokm':
            DEV_BLACKLIST.add(developer_address.lower())
        return False

    if market_cap < FILTERS.get('min_market_cap', 0):
        logging.info('Coin %s does not meet the minimum market cap filter. Skipping...', token_address)
        return False

    if volume_24h < FILTERS.get('min_volume_24h', 0):
        logging.info('Coin %s does not meet the minimum 24h volume filter. Skipping...', token_address)
        return False

    if check_fake_volume(coin):
        logging.info('Coin %s suspected of having fake volume. Skipping...', token_address)
        return False

    return True

def detect_events(coin):
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

    if price_change_1h <= -90:
        event = 'rug_pull'

    elif price_change_24h >= 100:
        event = 'pump'

    elif market_cap >= 1_000_000_000:
        event = 'tier_one'

    return event

async def process_data(data, engine):
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
            except Exception as e:
                logging.error('Error updating held token status: %s', e)
        else:
            logging.info('No rug_pull event detected for held token: %s (%s)', symbol, token_address)


async def main():
    load_blacklists()
    engine = get_engine()
    create_tables(engine)

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
    #asyncio.run(main())
    asyncio.run(buy_token('CXStz3QK8fGygd7ky6NrrU3ZfcJpwAKTvpBySawspump'))
