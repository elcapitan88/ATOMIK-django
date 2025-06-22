-- Script to add payout management columns to production database
-- Run this if the alembic migration jkl345mno678 hasn't been applied

-- Check current state
SELECT column_name 
FROM information_schema.columns 
WHERE table_name = 'affiliates' 
AND column_name IN ('payout_method', 'payout_details');

-- Add payout_method column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'affiliates' 
        AND column_name = 'payout_method'
    ) THEN
        ALTER TABLE affiliates ADD COLUMN payout_method VARCHAR;
        RAISE NOTICE 'Added payout_method column to affiliates table';
    ELSE
        RAISE NOTICE 'payout_method column already exists';
    END IF;
END $$;

-- Add payout_details column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'affiliates' 
        AND column_name = 'payout_details'
    ) THEN
        ALTER TABLE affiliates ADD COLUMN payout_details JSON;
        RAISE NOTICE 'Added payout_details column to affiliates table';
    ELSE
        RAISE NOTICE 'payout_details column already exists';
    END IF;
END $$;

-- Create affiliate_payouts table if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.tables 
        WHERE table_name = 'affiliate_payouts'
    ) THEN
        CREATE TABLE affiliate_payouts (
            id SERIAL PRIMARY KEY,
            affiliate_id INTEGER NOT NULL REFERENCES affiliates(id) ON DELETE CASCADE,
            payout_amount FLOAT NOT NULL,
            payout_method VARCHAR NOT NULL,
            payout_details JSON,
            period_start TIMESTAMP NOT NULL,
            period_end TIMESTAMP NOT NULL,
            status VARCHAR DEFAULT 'pending' NOT NULL,
            payout_date TIMESTAMP,
            transaction_id VARCHAR,
            currency VARCHAR DEFAULT 'USD' NOT NULL,
            commission_count INTEGER DEFAULT 0 NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW() NOT NULL
        );
        
        -- Create indexes
        CREATE INDEX ix_affiliate_payouts_id ON affiliate_payouts(id);
        CREATE INDEX ix_affiliate_payouts_affiliate_id ON affiliate_payouts(affiliate_id);
        CREATE INDEX ix_affiliate_payouts_status ON affiliate_payouts(status);
        CREATE INDEX ix_affiliate_payouts_period_end ON affiliate_payouts(period_end);
        CREATE INDEX ix_affiliate_payouts_payout_date ON affiliate_payouts(payout_date);
        
        RAISE NOTICE 'Created affiliate_payouts table with indexes';
    ELSE
        RAISE NOTICE 'affiliate_payouts table already exists';
    END IF;
END $$;

-- Update alembic version to mark this migration as complete
UPDATE alembic_version SET version_num = 'jkl345mno678' WHERE version_num = 'ghi012jkl345';

-- Verify the changes
SELECT 
    'Affiliates columns:' as info,
    column_name,
    data_type
FROM information_schema.columns 
WHERE table_name = 'affiliates' 
AND column_name IN ('payout_method', 'payout_details')
UNION ALL
SELECT 
    'Affiliate payouts table:' as info,
    table_name,
    'exists' as data_type
FROM information_schema.tables 
WHERE table_name = 'affiliate_payouts';

-- Show current alembic version
SELECT 'Current alembic version:' as info, version_num as column_name, '' as data_type
FROM alembic_version;