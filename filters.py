import logging
import requests

from solana.rpc.api import Client
from solana.publickey import PublicKey

from config import RUGCHECK, SOLANA, FILTERS

def check_rugcheck(token: str) -> bool:
    if not RUGCHECK.get('enabled', False):
        logging.info('RugCheck está desabilitado. Assumindo que o token é bom.')
        return True

    api_url_template = RUGCHECK.get('api_url')

    if not api_url_template:
        logging.warning('URL da API do RugCheck não está configurada.')
        return False

    api_url = api_url_template(token)

    try:
        response = requests.get(api_url, timeout=10)

        if response.status_code == 200:
            data = response.json()

            total_score = data.get('score', 0)

            if total_score > 5000:
                logging.info('Token %s possui um score total alto (%d). Considerado como "trash".', token, total_score)
                return False

            for risco in data.get('risks', []):
                nome = risco.get('name', '').lower()
                nivel = risco.get('level', '').lower()

                if nome in ['copycat token', 'low amount of lp providers']:
                    logging.debug('Risco "%s" identificado, mas será ignorado.', risco.get('name'))
                    continue

                if nivel == 'danger':
                    logging.info('Token %s possui risco crítico: "%s". Considerado como "trash".', token, risco.get('name'))
                    return False

            logging.info('Token %s passou na verificação do RugCheck. Considerado como bom.', token)
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

def check_bundled_supply(token: str) -> bool:
    try:
        client = Client(SOLANA.get('url'))

        try:
            mint_pubkey = PublicKey(token)
        except ValueError:
            logging.error("Invalid mint address provided.")

        response = client.get_token_largest_accounts(mint_pubkey)

        supply = client.get_token_supply(mint_pubkey).get('result', {}).get('value', {}).get('amount', 0)

        if response and response.get('result') and supply:
            data = response.get('result').get('value', [])
            total_supply = float(supply)

            if total_supply == 0:
                return False 

            top_holders_supply = sum(float(holder['amount']) for holder in data[:5])
            percentage = (top_holders_supply / total_supply) * 100

            if percentage > 50: 
                return True 
        else:
            logging.error('Error while fetching holders or supply:\nResponse: %s\nSupply: %s', response, supply)
            return False
    except Exception as e:
        logging.error('Exception in check_bundled_supply: %s', e)
        return False

    return False

def check_fake_volume(coin):
    market_cap = coin.get('fdv', 0)
    volume_24h = coin.get('volume', {}).get('h24', 0)
    price_change_24h = coin.get('priceChange', {}).get('h24', 0)

    try:
        volume_24h = float(volume_24h)
        market_cap = float(market_cap)
        price_change_24h = float(price_change_24h)
    except (ValueError, TypeError):
        return True

    if market_cap > 0:
        ratio = volume_24h / market_cap
    else:
        ratio = float('inf')

    max_ratio = FILTERS.get('max_volume_market_cap_ratio', float('inf'))

    if ratio > max_ratio:
        logging.info('Coin %s has high volume-to-market cap ratio (%.2f). Suspected fake volume.', coin.get('address'), ratio)
        return True

    if volume_24h > FILTERS.get('min_volume_24h', 0) and abs(price_change_24h) < 1:
        logging.info('Coin %s has high volume but minimal price change. Suspected fake volume.', coin.get('address'))
        return True

    return False