from fastapi import APIRouter, Depends
from typing import Dict, Any
from datetime import datetime, timedelta

from app.utils.futures_contracts import FuturesContractManager
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/current", response_model=Dict[str, str])
async def get_current_contracts() -> Dict[str, str]:
    """
    Get current futures contract mappings.
    
    Returns a dictionary mapping base symbols to current contract symbols.
    Example: {"ES": "ESU5", "NQ": "NQU5", ...}
    
    This endpoint is public as contract information is market data.
    """
    return FuturesContractManager.get_current_contracts()


@router.get("/info", response_model=Dict[str, Any])
async def get_contract_info() -> Dict[str, Any]:
    """
    Get comprehensive contract information including rollover dates.
    
    Returns:
    - Current contract mappings
    - Next rollover date
    - Days until rollover
    - Current contract month and year
    """
    return FuturesContractManager.get_contract_info()


@router.get("/next-rollover", response_model=Dict[str, Any])
async def get_next_rollover() -> Dict[str, Any]:
    """
    Get information about the next contract rollover.
    
    Returns the date and contracts that will be active after the rollover.
    """
    current_date = datetime.now()
    next_rollover_date = FuturesContractManager.get_next_rollover_date()
    
    # Calculate what contracts will be active after rollover
    # by using a date just after the next rollover
    future_date = next_rollover_date + timedelta(days=1)
    month_code, year_suffix = FuturesContractManager.get_current_contract_month_year(future_date)
    
    future_contracts = {}
    for symbol in FuturesContractManager.FUTURES_SYMBOLS:
        future_contracts[symbol] = f"{symbol}{month_code}{year_suffix}"
    
    return {
        "rollover_date": next_rollover_date.isoformat(),
        "days_until_rollover": (next_rollover_date - current_date).days,
        "current_contracts": FuturesContractManager.get_current_contracts(),
        "next_contracts": future_contracts,
        "next_month": month_code,
        "next_year": f"202{year_suffix}"
    }


@router.get("/symbol/{symbol}", response_model=Dict[str, str])
async def get_contract_for_symbol(symbol: str) -> Dict[str, str]:
    """
    Get the current contract for a specific symbol.
    
    Args:
        symbol: Base symbol (e.g., "ES", "NQ")
    
    Returns:
        Dictionary with base symbol and current contract
    """
    symbol = symbol.upper()
    contracts = FuturesContractManager.get_current_contracts()
    
    if symbol not in contracts:
        return {
            "error": f"Symbol {symbol} not found",
            "available_symbols": list(contracts.keys())
        }
    
    return {
        "symbol": symbol,
        "contract": contracts[symbol],
        "month": FuturesContractManager.get_current_contract_month_year()[0],
        "year": f"202{FuturesContractManager.get_current_contract_month_year()[1]}"
    }