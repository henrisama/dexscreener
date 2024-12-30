import base58
import logging

from utils import send_telegram_message
from config import WALLET, SOLANA, TRADING

from solana.rpc.api import Client
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.rpc.core import RPCException
from solana.transaction import Transaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts, TxOpts
from solana.system_program import TransferParams, transfer

def load_wallet() -> Keypair:
    try:
        secret_key = WALLET.get('secret_key', '')
        secret_key_bytes = base58.b58decode(secret_key)
        keypair = Keypair.from_secret_key(secret_key_bytes)

        return keypair
            
    except Exception as e:
        logging.error('Erro ao carregar a carteira: %s', e)

async def get_token_balance(token: str) -> float:
    try:
        wallet = load_wallet()
        client = Client(SOLANA.get('url'))
        token_mint_pubkey = PublicKey(token)


        response = client.get_token_accounts_by_owner(wallet.public_key, opts=TokenAccountOpts(mint=token_mint_pubkey))
        token_accounts = response['result']['value']
        total_balance = 0

        for account in token_accounts:
            account_pubkey = account['pubkey']
            balance_response = client.get_token_account_balance(account_pubkey)
            balance = balance_response['result']['value']['uiAmount']
            total_balance += balance

        return total_balance
    except Exception as e:
        logging.error('Erro ao obter saldo do token %s: %s', token, e)
        return 0

async def buy_token(token: str) -> None:
    try:
        wallet = load_wallet()
        client = Client(SOLANA.get('url'))
        amount = TRADING.get('trade_amount', 0.005)

        dex_address = PublicKey("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")

        transaction = Transaction().add(
            transfer(
                TransferParams(
                    from_pubkey=wallet.public_key,
                    to_pubkey=dex_address,
                    lamports=int(amount * 1e9)
                )
            )
        )

        print(transaction)
        response = await client.send_transaction(transaction, wallet, opts=TxOpts(preflight_commitment="confirmed"))
        print(response)
        logging.info(f'Compra executada com sucesso. TxID: {response["result"]}')
        await send_telegram_message(f'Compra executada: {amount} SOL para {token}. TxID: {response["result"]}')
    except Exception as e:
        print(e.with_traceback())
        logging.error('Erro ao comprar token: %s', e)
        await send_telegram_message(f'Erro ao comprar token: {e}')
