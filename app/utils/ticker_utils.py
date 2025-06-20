from typing import Dict, List, Tuple
from .futures_contracts import FuturesContractManager, get_current_futures_contracts

def get_tickers() -> Dict[str, str]:
    """Get current futures contract mappings"""
    return get_current_futures_contracts()

def get_display_tickers() -> List[str]:
    """Get display tickers for validation"""
    return FuturesContractManager.FUTURES_SYMBOLS

def get_contract_ticker(display_ticker: str) -> str:
    """Get full contract spec for a display ticker"""
    contracts = get_current_futures_contracts()
    return contracts.get(display_ticker, display_ticker)

def get_display_ticker(contract_ticker: str) -> str:
    """Convert full contract to display ticker"""
    # First check if it's already a display ticker
    if contract_ticker in FuturesContractManager.FUTURES_SYMBOLS:
        return contract_ticker
    
    # Extract base symbol from contract ticker (e.g., "ESU5" -> "ES")
    for symbol in FuturesContractManager.FUTURES_SYMBOLS:
        if contract_ticker.startswith(symbol):
            return symbol
    
    return contract_ticker

def validate_ticker(ticker: str) -> Tuple[bool, str]:
    """
    Validate if a ticker is supported.
    Accepts both display tickers (ES) and contract tickers (ESU5).
    """
    # Check if it's a valid display ticker (e.g., "ES")
    if ticker in FuturesContractManager.FUTURES_SYMBOLS:
        return True, get_contract_ticker(ticker)
    
    # Check if it's a valid contract ticker (e.g., "ESU5")
    # Extract base symbol and validate
    for symbol in FuturesContractManager.FUTURES_SYMBOLS:
        if ticker.startswith(symbol) and len(ticker) == len(symbol) + 2:
            # Verify it matches current contract format
            current_contracts = get_current_futures_contracts()
            if ticker == current_contracts.get(symbol):
                return True, ticker
            # Even if not current contract, still valid format
            return True, ticker
    
    return False, ""