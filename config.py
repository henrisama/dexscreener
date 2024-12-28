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

DEXSCREENER = {
    'latest': 'https://api.dexscreener.com/token-profiles/latest/v1',
    'pairs': 'https://api.dexscreener.com/latest/dex/tokens'
}

# Filters
FILTERS = {
    'min_market_cap': 1_000_000,     # Minimum market cap in USD
    'min_volume_24h': 10_000,        # Minimum 24h volume in USD
    'max_volume_market_cap_ratio': 1,  # Maximum acceptable volume-to-market cap ratio
}

# Coin Blacklist (list of token addresses to ignore)
COIN_BLACKLIST = set([
    # Pre-populated with known bad tokens
])

# Developer Blacklist (list of developer addresses to ignore)
DEV_BLACKLIST = set([
    # Pre-populated with known bad developers
])

# Pocket Universe API Configuration
POCKET_UNIVERSE = {
    'enabled': True,
    'api_key': 'your_pocket_universe_api_key',
    'api_url': 'https://api.pocketuniverse.app/v1/scams',
}

# RugCheck.xyz API Configuration
RUGCHECK = {
    'enabled': True,
    'api_url': lambda x : f'https://api.rugcheck.xyz/v1/tokens/{x}/report/summary',
}

# Telegram Bot Configuration
TELEGRAM = {
    'bot_token': 'your_telegram_bot_token',
    'chat_id': 'your_chat_id',
}

# BonkBot Configuration
BONKBOT = {
    'enabled': False,
    'username': 'BonkBot',
}

# Trading Configuration
TRADING = {
    'enabled': False,
    'trade_amount': 0.005 # ~1 USD in SOL
}

SOLANA = {
    'url': os.getenv('RPC_SOLANA'),
}
