import os
from typing import Dict, List, Tuple

def get_tickers() -> Dict[str, str]:
    """Parse tickers from environment variables"""
    ticker_string = os.getenv('FUTURES_TICKERS', '')
    ticker_pairs = ticker_string.split(',')
    
    ticker_map = {}
    for pair in ticker_pairs:
        if ':' in pair:
            display, contract = pair.split(':')
            ticker_map[display] = contract
    
    return ticker_map

def get_display_tickers() -> List[str]:
    """Get display tickers for validation"""
    return list(get_tickers().keys())

def get_contract_ticker(display_ticker: str) -> str:
    """Get full contract spec for a display ticker"""
    tickers = get_tickers()
    return tickers.get(display_ticker, display_ticker)

def get_display_ticker(contract_ticker: str) -> str:
    """Convert full contract to display ticker"""
    tickers = get_tickers()
    for display, contract in tickers.items():
        if contract == contract_ticker:
            return display
    return contract_ticker

def validate_ticker(ticker: str) -> Tuple[bool, str]:
    """Validate if a ticker is supported"""
    tickers = get_tickers()
    
    # Check if it's a valid display ticker
    if ticker in tickers:
        return True, get_contract_ticker(ticker)
    
    # Check if it's a valid contract ticker
    if ticker in tickers.values():
        return True, ticker
        
    return False, ""