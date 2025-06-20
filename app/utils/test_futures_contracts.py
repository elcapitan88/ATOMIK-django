import pytest
from datetime import datetime
from futures_contracts import FuturesContractManager


class TestFuturesContractManager:
    """Test suite for FuturesContractManager."""
    
    def test_get_third_monday(self):
        """Test calculation of third Monday."""
        # Test known third Mondays
        test_cases = [
            # (year, month, expected_day)
            (2025, 3, 17),   # March 17, 2025
            (2025, 6, 16),   # June 16, 2025
            (2025, 9, 15),   # September 15, 2025
            (2025, 12, 15),  # December 15, 2025
            (2024, 3, 18),   # March 18, 2024
            (2024, 6, 17),   # June 17, 2024
            (2024, 9, 16),   # September 16, 2024
            (2024, 12, 16),  # December 16, 2024
        ]
        
        for year, month, expected_day in test_cases:
            third_monday = FuturesContractManager.get_third_monday(year, month)
            assert third_monday.day == expected_day
            assert third_monday.weekday() == 0  # 0 is Monday
            assert third_monday.year == year
            assert third_monday.month == month
    
    def test_get_current_contract_month_year(self):
        """Test contract month/year determination."""
        # Test cases: (reference_date, expected_month_code, expected_year_suffix)
        test_cases = [
            # Before March rollover (17th)
            (datetime(2025, 3, 10), 'H', '5'),  # March contract
            (datetime(2025, 3, 16), 'H', '5'),  # Day before rollover
            
            # After March rollover
            (datetime(2025, 3, 17), 'M', '5'),  # June contract
            (datetime(2025, 3, 20), 'M', '5'),  # June contract
            
            # Before June rollover
            (datetime(2025, 6, 15), 'M', '5'),  # June contract
            
            # After June rollover
            (datetime(2025, 6, 16), 'U', '5'),  # September contract
            
            # Before September rollover
            (datetime(2025, 9, 14), 'U', '5'),  # September contract
            
            # After September rollover
            (datetime(2025, 9, 15), 'Z', '5'),  # December contract
            
            # Before December rollover
            (datetime(2025, 12, 14), 'Z', '5'),  # December contract
            
            # After December rollover - rolls to next year March
            (datetime(2025, 12, 15), 'H', '6'),  # March 2026
            (datetime(2025, 12, 31), 'H', '6'),  # March 2026
            (datetime(2026, 1, 1), 'H', '6'),   # March 2026
            (datetime(2026, 3, 15), 'H', '6'),  # Still March 2026
        ]
        
        for reference_date, expected_month, expected_year in test_cases:
            month_code, year_suffix = FuturesContractManager.get_current_contract_month_year(reference_date)
            assert month_code == expected_month, f"Failed for {reference_date}: expected {expected_month}, got {month_code}"
            assert year_suffix == expected_year, f"Failed for {reference_date}: expected year {expected_year}, got {year_suffix}"
    
    def test_get_next_rollover_date(self):
        """Test next rollover date calculation."""
        test_cases = [
            # (reference_date, expected_rollover_month, expected_rollover_day)
            (datetime(2025, 1, 1), 3, 17),    # Next is March 17
            (datetime(2025, 3, 16), 3, 17),   # Next is March 17 (day before)
            (datetime(2025, 3, 17), 6, 16),   # Next is June 16 (on rollover day)
            (datetime(2025, 6, 1), 6, 16),    # Next is June 16
            (datetime(2025, 6, 16), 9, 15),   # Next is September 15
            (datetime(2025, 9, 15), 12, 15),  # Next is December 15
            (datetime(2025, 12, 15), 3, 16),  # Next is March 16, 2026
            (datetime(2025, 12, 31), 3, 16),  # Next is March 16, 2026
        ]
        
        for reference_date, expected_month, expected_day in test_cases:
            next_rollover = FuturesContractManager.get_next_rollover_date(reference_date)
            assert next_rollover.month == expected_month
            assert next_rollover.day == expected_day
            # Handle year transition
            if reference_date.month == 12 and expected_month == 3:
                assert next_rollover.year == reference_date.year + 1
            else:
                assert next_rollover.year == reference_date.year
    
    def test_get_current_contracts(self):
        """Test contract mapping generation."""
        # Mock a specific date
        test_date = datetime(2025, 6, 1)  # Should be in June contract (M5)
        
        # Temporarily override the method to use our test date
        original_method = FuturesContractManager.get_current_contract_month_year
        FuturesContractManager.get_current_contract_month_year = lambda ref_date=None: ('M', '5')
        
        try:
            contracts = FuturesContractManager.get_current_contracts()
            
            # Check all expected symbols
            expected_symbols = ['ES', 'NQ', 'CL', 'GC', 'MES', 'MNQ', 'RTY', 'YM']
            for symbol in expected_symbols:
                assert symbol in contracts
                assert contracts[symbol] == f"{symbol}M5"
        finally:
            # Restore original method
            FuturesContractManager.get_current_contract_month_year = original_method
    
    def test_get_contract_info(self):
        """Test comprehensive contract info."""
        info = FuturesContractManager.get_contract_info()
        
        # Check required fields
        assert 'contracts' in info
        assert 'current_month' in info
        assert 'current_year' in info
        assert 'next_rollover_date' in info
        assert 'days_until_rollover' in info
        assert 'generated_at' in info
        
        # Validate contracts
        assert isinstance(info['contracts'], dict)
        assert len(info['contracts']) == 8  # 8 symbols
        
        # Validate date formats
        datetime.fromisoformat(info['next_rollover_date'])
        datetime.fromisoformat(info['generated_at'])
        
        # Validate days until rollover
        assert isinstance(info['days_until_rollover'], int)
        assert info['days_until_rollover'] >= 0
    
    def test_contract_codes(self):
        """Test that contract codes are correct."""
        assert FuturesContractManager.CONTRACT_MONTHS == {
            3: 'H',
            6: 'M',
            9: 'U',
            12: 'Z'
        }
    
    def test_futures_symbols(self):
        """Test that all required futures symbols are present."""
        expected_symbols = ['ES', 'NQ', 'CL', 'GC', 'MES', 'MNQ', 'RTY', 'YM']
        assert FuturesContractManager.FUTURES_SYMBOLS == expected_symbols


# Utility function tests
def test_get_current_futures_contracts():
    """Test the convenience function."""
    from futures_contracts import get_current_futures_contracts
    contracts = get_current_futures_contracts()
    assert isinstance(contracts, dict)
    assert len(contracts) == 8


def test_get_contract_for_symbol():
    """Test getting contract for specific symbol."""
    from futures_contracts import get_contract_for_symbol
    
    # Test valid symbol
    contract = get_contract_for_symbol('ES')
    assert contract.startswith('ES')
    assert len(contract) == 4  # e.g., 'ESM5'
    
    # Test invalid symbol - should return the original
    contract = get_contract_for_symbol('INVALID')
    assert contract == 'INVALID'


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])