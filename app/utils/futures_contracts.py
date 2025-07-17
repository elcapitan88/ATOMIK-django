from datetime import datetime, timedelta
from typing import Dict, Tuple
import calendar


class FuturesContractManager:
    """Manages futures contract symbols and automatic quarterly rollovers."""
    
    # Contract month codes for quarterly contracts
    CONTRACT_MONTHS = {
        3: 'H',   # March
        6: 'M',   # June
        9: 'U',   # September
        12: 'Z'   # December
    }
    
    # Contract month codes for monthly contracts
    MONTHLY_CONTRACT_MONTHS = {
        1: 'F',   # January
        2: 'G',   # February
        3: 'H',   # March
        4: 'J',   # April
        5: 'K',   # May
        6: 'M',   # June
        7: 'N',   # July
        8: 'Q',   # August
        9: 'U',   # September
        10: 'V',  # October
        11: 'X',  # November
        12: 'Z'   # December
    }
    
    # Base symbols for futures contracts (quarterly)
    FUTURES_SYMBOLS = ['ES', 'NQ', 'CL', 'GC', 'MES', 'MNQ', 'RTY', 'YM']
    
    # Monthly expiring futures contracts
    MONTHLY_FUTURES_SYMBOLS = ['MBT']
    
    @staticmethod
    def get_third_monday(year: int, month: int) -> datetime:
        """Calculate the third Monday of a given month."""
        # Find the first day of the month
        first_day = datetime(year, month, 1)
        
        # Find the first Monday
        days_until_monday = (7 - first_day.weekday()) % 7
        if days_until_monday == 0 and first_day.weekday() == 0:
            first_monday = first_day
        else:
            first_monday = first_day + timedelta(days=days_until_monday)
        
        # Add 14 days to get the third Monday
        third_monday = first_monday + timedelta(days=14)
        return third_monday
    
    @staticmethod
    def get_monday_before_third_friday(year: int, month: int) -> datetime:
        """Calculate the Monday preceding the third Friday of a given month."""
        # Find the first day of the month
        first_day = datetime(year, month, 1)
        
        # Find the first Friday (weekday 4)
        days_until_friday = (4 - first_day.weekday()) % 7
        if days_until_friday == 0 and first_day.weekday() == 4:
            first_friday = first_day
        else:
            first_friday = first_day + timedelta(days=days_until_friday)
        
        # Add 14 days to get the third Friday
        third_friday = first_friday + timedelta(days=14)
        
        # Go back to the preceding Monday (subtract days based on weekday)
        # If third Friday is on Friday (4), we need to go back 4 days to Monday (0)
        days_back = (third_friday.weekday() - 0) % 7
        if days_back == 0:
            # If third Friday is actually a Monday, go back 7 days
            days_back = 7
        monday_before = third_friday - timedelta(days=days_back)
        
        return monday_before
    
    @staticmethod
    def get_current_monthly_contract(reference_date: datetime = None) -> Tuple[str, str]:
        """
        Determine the current contract month and year for monthly contracts.
        Monthly contracts roll on the third Monday of each month.
        
        Returns:
            Tuple of (month_code, year_suffix)
            Example: ('Q', '5') for August 2025
        """
        if reference_date is None:
            reference_date = datetime.now()
        
        current_year = reference_date.year
        current_month = reference_date.month
        
        # Check if we're before the rollover date of current month
        rollover_date = FuturesContractManager.get_monday_before_third_friday(current_year, current_month)
        
        if reference_date < rollover_date:
            # Use current month
            contract_month = current_month
            contract_year = current_year
        else:
            # Use next month
            if current_month == 12:
                contract_month = 1
                contract_year = current_year + 1
            else:
                contract_month = current_month + 1
                contract_year = current_year
        
        # Get month code and year suffix
        month_code = FuturesContractManager.MONTHLY_CONTRACT_MONTHS[contract_month]
        year_suffix = str(contract_year)[-1]  # Last digit of year
        
        return month_code, year_suffix
    
    @staticmethod
    def get_current_contract_month_year(reference_date: datetime = None) -> Tuple[str, str]:
        """
        Determine the current contract month and year based on rollover rules.
        Contracts roll on the third Monday of March, June, September, and December.
        
        Returns:
            Tuple of (month_code, year_suffix)
            Example: ('U', '5') for September 2025
        """
        if reference_date is None:
            reference_date = datetime.now()
        
        current_year = reference_date.year
        current_month = reference_date.month
        
        # Quarterly months
        quarterly_months = [3, 6, 9, 12]
        
        # Find the next contract month
        for month in quarterly_months:
            if current_month <= month:
                # Check if we're before the rollover date
                rollover_date = FuturesContractManager.get_third_monday(current_year, month)
                
                if reference_date < rollover_date:
                    contract_month = month
                    contract_year = current_year
                    break
        else:
            # We're past December rollover, use March of next year
            contract_month = 3
            contract_year = current_year + 1
        
        # Get month code and year suffix
        month_code = FuturesContractManager.CONTRACT_MONTHS[contract_month]
        year_suffix = str(contract_year)[-1]  # Last digit of year
        
        return month_code, year_suffix
    
    @staticmethod
    def get_next_rollover_date(reference_date: datetime = None) -> datetime:
        """Get the next contract rollover date."""
        if reference_date is None:
            reference_date = datetime.now()
        
        current_year = reference_date.year
        quarterly_months = [3, 6, 9, 12]
        
        # Find the next rollover date
        for month in quarterly_months:
            rollover_date = FuturesContractManager.get_third_monday(current_year, month)
            if reference_date < rollover_date:
                return rollover_date
        
        # If we're past December, return March of next year
        return FuturesContractManager.get_third_monday(current_year + 1, 3)
    
    @staticmethod
    def get_current_contracts() -> Dict[str, str]:
        """
        Get the current contract mapping for all futures symbols.
        
        Returns:
            Dictionary mapping display symbols to contract symbols
            Example: {'ES': 'ESU5', 'NQ': 'NQU5', 'MBT': 'MBTQ5', ...}
        """
        contracts = {}
        
        # Handle quarterly contracts
        month_code, year_suffix = FuturesContractManager.get_current_contract_month_year()
        for symbol in FuturesContractManager.FUTURES_SYMBOLS:
            contracts[symbol] = f"{symbol}{month_code}{year_suffix}"
        
        # Handle monthly contracts
        monthly_month_code, monthly_year_suffix = FuturesContractManager.get_current_monthly_contract()
        for symbol in FuturesContractManager.MONTHLY_FUTURES_SYMBOLS:
            contracts[symbol] = f"{symbol}{monthly_month_code}{monthly_year_suffix}"
        
        return contracts
    
    @staticmethod
    def get_contract_info() -> Dict:
        """
        Get comprehensive contract information including current contracts and rollover date.
        
        Returns:
            Dictionary with contract mappings and metadata
        """
        current_date = datetime.now()
        month_code, year_suffix = FuturesContractManager.get_current_contract_month_year()
        next_rollover = FuturesContractManager.get_next_rollover_date()
        
        return {
            "contracts": FuturesContractManager.get_current_contracts(),
            "current_month": month_code,
            "current_year": f"202{year_suffix}",  # Assuming 2020s
            "next_rollover_date": next_rollover.isoformat(),
            "days_until_rollover": (next_rollover - current_date).days,
            "generated_at": current_date.isoformat()
        }


# Utility functions for direct use
def get_current_futures_contracts() -> Dict[str, str]:
    """Convenience function to get current contract mappings."""
    return FuturesContractManager.get_current_contracts()


def get_contract_for_symbol(symbol: str) -> str:
    """Get the current contract for a specific symbol."""
    contracts = FuturesContractManager.get_current_contracts()
    return contracts.get(symbol, symbol)  # Return original if not found


def is_monthly_contract(symbol: str) -> bool:
    """Check if a symbol is a monthly contract."""
    return symbol in FuturesContractManager.MONTHLY_FUTURES_SYMBOLS