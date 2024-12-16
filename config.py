# config.py
import os
from dotenv import load_dotenv
load_dotenv()

DATABASE = {
    'drivername': 'postgresql',
    'host': 'localhost',
    'port': '5432',
    'username': 'postgres',    
    'password': '1234',    
    'database': 'dexscreenerdb'    
}

API_URL = 'https://api.dexscreener.com/token-profiles/latest/v1' 

# Filters
FILTERS = {
    'min_market_cap': 1_000_000,     # Minimum market cap in USD
    'min_volume_24h': 10_000,        # Minimum 24h volume in USD
    'max_volume_market_cap_ratio': 1,  # Maximum acceptable volume-to-market cap ratio
    # Add other filters as required
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
    'bot_token': 'your_telegram_bot_token',  # Replace with your Telegram bot token
    'chat_id': 'your_chat_id',  # Replace with your Telegram chat ID
}

# BonkBot Configuration
BONKBOT = {
    'enabled': True,
    'username': 'BonkBot',  # BonkBot's Telegram username
    # Additional configuration if required
}

# Trading Configuration
TRADING = {
    'enabled': True,
    'trade_amount': 0.1,  # Amount in ETH or the base currency to use for trades
    # Additional trading parameters
}

SOLANA = {
    url: os.getenv('URL_SOLANA'),
}
