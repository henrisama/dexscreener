# config.py
import os

from dotenv import load_dotenv
load_dotenv()

DATABASE = {
    'drivername': 'postgresql',
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT'),
    'username': os.getenv('DB_USER'),    
    'password': os.getenv('DB_PASS'),    
    'database': os.getenv('DB_NAME'),   
}

WALLET = {
    'secret_key': os.getenv('WALLET_SECRET_KEY'),
}

DEXSCREENER = {
    'latest': 'https://api.dexscreener.com/token-profiles/latest/v1',
    'pairs': 'https://api.dexscreener.com/latest/dex/tokens'
}

FILTERS = {
    'min_market_cap': 1_000_000,     # Minimum market cap in USD
    'min_volume_24h': 10_000,        # Minimum 24h volume in USD
    'max_volume_market_cap_ratio': 1,  # Maximum acceptable volume-to-market cap ratio
}

COIN_BLACKLIST = set([
    # Pre-populated with known bad tokens
])

DEV_BLACKLIST = set([
    # Pre-populated with known bad developers
])

RUGCHECK = {
    'enabled': True,
    'api_url': lambda x : f'https://api.rugcheck.xyz/v1/tokens/{x}/report/summary',
}

TELEGRAM = {
    'bot_token': os.getenv('TELEGRAM_BOT_TOKEN'),
    'chat_id': os.getenv('TELEGRAM_CHAT_ID'),
}

TRADING = {
    'enabled': False,
    'trade_amount': 0.005 # ~1 USD in SOL
}

SOLANA = {
    'url': 'https://api.mainnet-beta.solana.com',
}
