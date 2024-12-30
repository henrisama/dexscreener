import json
import base64
import logging
import requests
from telegram import Bot

from config import TELEGRAM, SOLANA, COIN_BLACKLIST, DEV_BLACKLIST, DEXSCREENER

from solana.rpc.api import Client
from solana.publickey import PublicKey

BLACKLIST_FILE = 'blacklists.json'
telegram_bot = Bot(token=TELEGRAM['bot_token'])
METAPLEX_PROGRAM_ID = PublicKey("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")

async def send_telegram_message(message: str) -> None:
    try:
        await telegram_bot.send_message(chat_id=TELEGRAM['chat_id'], text=message)
        logging.info('Sent Telegram message: %s', message)
    except Exception as e:
        logging.error('Error sending Telegram message: %s', e)

def find_metadata_pda(mint: PublicKey) -> PublicKey:
    seeds = [
        b"metadata",
        bytes(METAPLEX_PROGRAM_ID),
        bytes(mint)
    ]
    metadata_pda, _ = PublicKey.find_program_address(seeds, METAPLEX_PROGRAM_ID)
    return metadata_pda

def get_developer_address(token: str) -> str:
    try:
        client = Client(SOLANA.get('url'))

        try:
            mint_pubkey = PublicKey(token)
        except ValueError:
            logging.error("Invalid mint address provided.")

        metadata_pda = find_metadata_pda(mint_pubkey)

        response = client.get_account_info(metadata_pda)
        account_info = response.get('result', {}).get('value')

        if not account_info:
            logging.error("Metadata account not found for the given mint address.")

        data_base64 = account_info.get('data', [])[0]
        if not data_base64:
            logging.error("No data found in the metadata account.")

        try:
            decoded_data = base64.b64decode(data_base64)
        except base64.binascii.Error:
            logging.error("Failed to decode account data.")

        try:
            update_authority_bytes = decoded_data[1:33]
            update_authority_pubkey = PublicKey(update_authority_bytes)
            return str(update_authority_pubkey)
        except Exception as e:
            logging.error(f"Failed to extract update authority: {e}")
    except Exception as e:
        logging.error('Error fetching developer address from Solscan: %s', e)
        return None

def load_blacklists():
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

def get_token_data(token_address):
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