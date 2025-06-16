# Async Context Manager Issues in Webhook Execution Pipeline

## Problem Summary

The webhook execution pipeline was failing with `__aenter__` errors when using the complex async infrastructure (rollback manager, distributed locks, circuit breakers). We implemented a temporary workaround using direct broker execution, but the async infrastructure should be properly integrated for production use.

## Current Status

- ✅ **WORKING**: Direct broker execution (temporary workaround)
- ❌ **BROKEN**: Full async infrastructure with rollback/lock management
- 🎯 **GOAL**: Integrate async infrastructure correctly for robust production execution

## Error Details

### Primary Error Signature
```
Error during locked operation for account 21610093: __aenter__
Transaction failed: strategy_execution [strategy_316_1749489781] - __aenter__
Circuit breaker recorded failure for strategy_316: __aenter__
```

### Error Location
The `__aenter__` error occurs in the `_execute_strategy_with_rollback` method when entering async context managers:

```python
# app/services/strategy_service.py:253-275
async with rollback_manager.transaction_context(
    "strategy_execution",
    f"strategy_{strategy.id}_{int(time.time())}"
) as rollback_ctx:
    
    async with AccountLockManager.lock_account(
        account_id=strategy.account_id,
        timeout=30.0,
        max_retries=3,
        operation_name=f"strategy_{strategy.id}_execution"
    ) as lock_acquired:
        
        # Further nested async context managers...
        async with rollback_ctx.database_transaction() as db:
```

## Root Cause Analysis

### 1. Session Type Mismatch
- **Railway Processor**: Uses `AsyncSession` from SQLAlchemy
- **Strategy Service**: Expects sync `Session` but uses async patterns
- **Conflict**: Async context managers can't properly initialize with wrong session type

### 2. Context Manager Chain Issues
The execution path involves multiple nested async context managers:
```
rollback_manager.transaction_context()
├── AccountLockManager.lock_account()
    ├── rollback_ctx.database_transaction()
        ├── broker.place_order()
```

### 3. Database Session Inconsistency
```python
# Railway processor creates AsyncSession
self.db = AsyncSession(...)

# But StrategyProcessor expects sync Session
strategy_processor = StrategyProcessor(self.db)  # ❌ Wrong session type
```

## Architecture Components

### 1. Railway Webhook Processor
**File**: `app/services/webhook_service.py:445-714`
**Purpose**: Ultra-fast webhook processing for high-frequency trading
**Session**: `AsyncSession`

```python
class RailwayOptimizedWebhookProcessor:
    def __init__(self, db: AsyncSession):
        self.db = db  # AsyncSession
```

### 2. Strategy Service
**File**: `app/services/strategy_service.py:165-733`
**Purpose**: Execute trading strategies with full transaction safety
**Session**: Expects sync `Session` but uses async patterns

```python
class StrategyProcessor:
    def __init__(self, db: Session):  # Expects sync Session
        self.db = db
```

### 3. Rollback Manager
**File**: `app/core/rollback_manager.py`
**Purpose**: Transaction safety with automatic rollback on failures
**Pattern**: Async context manager

### 4. Distributed Lock Manager
**File**: `app/services/distributed_lock.py`
**Purpose**: Account-level locking to prevent race conditions
**Pattern**: Async context manager

### 5. Circuit Breaker
**File**: `app/core/circuit_breaker.py`
**Purpose**: Prevent repeated failures from cascading
**Pattern**: Async execution wrapper

## Current Workaround Implementation

### Direct Broker Execution (app/services/webhook_service.py:645-725)
```python
async def _process_strategy_async(self, strategy, signal_data):
    # Bypass complex async infrastructure
    with SessionLocal() as sync_db:
        # Direct broker execution
        account = sync_db.query(BrokerAccount).filter(...)
        broker = BaseBroker.get_broker_instance(account.broker_id, sync_db)
        order_result = await broker.place_order(account, order_data)
```

**Pros**:
- ✅ Works reliably
- ✅ Fast execution
- ✅ Simple debugging

**Cons**:
- ❌ No transaction rollback protection
- ❌ No distributed locking (race conditions possible)
- ❌ No circuit breaker protection
- ❌ Limited error recovery

## Integration Solutions

### Option 1: Make Strategy Service Fully Async
**Approach**: Convert StrategyProcessor to use AsyncSession consistently

```python
class StrategyProcessor:
    def __init__(self, db: AsyncSession):  # Accept AsyncSession
        self.db = db
    
    async def _execute_strategy_with_rollback(self, strategy, signal_data):
        # Keep existing async infrastructure
        async with rollback_manager.transaction_context(...) as rollback_ctx:
            async with AccountLockManager.lock_account(...) as lock_acquired:
                async with rollback_ctx.database_transaction() as db:
                    # Use async database operations
                    account = await db.execute(select(BrokerAccount).where(...))
```

**Changes Required**:
- Convert all database queries to async (`db.execute(select(...))`)
- Update all database commits to async (`await db.commit()`)
- Ensure all context managers work with AsyncSession
- Test rollback functionality with async sessions

### Option 2: Create Async-Compatible Context Managers
**Approach**: Modify context managers to work with both sync and async sessions

```python
class HybridRollbackManager:
    def transaction_context(self, session_type="sync"):
        if isinstance(self.db, AsyncSession):
            return self._async_transaction_context()
        else:
            return self._sync_transaction_context()
```

### Option 3: Session Bridge Pattern
**Approach**: Create a bridge between async and sync sessions

```python
class SessionBridge:
    def __init__(self, async_session: AsyncSession):
        self.async_session = async_session
    
    def get_sync_session(self):
        # Create sync session with same connection
        return Session(bind=self.async_session.bind)
```

## Testing Strategy

### 1. Unit Tests Required
- [ ] Test async context manager initialization
- [ ] Test session type compatibility
- [ ] Test rollback functionality with AsyncSession
- [ ] Test distributed lock behavior
- [ ] Test circuit breaker with async execution

### 2. Integration Tests Required
- [ ] End-to-end webhook execution with async infrastructure
- [ ] Concurrent execution testing (race conditions)
- [ ] Failure scenario testing (rollback verification)
- [ ] Performance comparison (async vs direct execution)

### 3. Load Testing Required
- [ ] High-frequency webhook execution
- [ ] Multiple concurrent strategies
- [ ] Database connection pool stress testing

## Technical Specifications

### Database Sessions
```python
# Current working (direct execution)
with SessionLocal() as sync_db:
    strategy_processor = StrategyProcessor(sync_db)

# Target (async infrastructure)
async with AsyncSessionLocal() as async_db:
    strategy_processor = AsyncStrategyProcessor(async_db)
```

### Context Manager Pattern
```python
# Current pattern causing issues
async with rollback_manager.transaction_context() as ctx:
    async with AccountLockManager.lock_account() as lock:
        async with ctx.database_transaction() as db:
            # Database operations

# Target pattern (working)
async with async_rollback_manager.transaction_context() as ctx:
    async with AsyncAccountLockManager.lock_account() as lock:
        async with ctx.async_database_transaction() as db:
            # Async database operations
```

## Files to Investigate

### Primary Files
1. `app/services/strategy_service.py` - Main strategy execution logic
2. `app/services/webhook_service.py` - Railway processor implementation
3. `app/core/rollback_manager.py` - Transaction rollback management
4. `app/services/distributed_lock.py` - Account locking mechanism
5. `app/core/circuit_breaker.py` - Circuit breaker implementation

### Supporting Files
1. `app/db/session.py` - Database session configuration
2. `app/models/broker.py` - Broker account models
3. `app/core/brokers/base.py` - Broker base class
4. `app/core/brokers/implementations/tradovate.py` - Tradovate broker

## Error Logs for Reference

### Full Error Context
```
2025-06-09 17:23:01,844 - app.core.rollback_manager - INFO - Started transaction context: strategy_execution
2025-06-09 17:23:01,844 - app.services.distributed_lock - INFO - Attempting to acquire lock for account 21610093
2025-06-09 17:23:01,848 - app.services.distributed_lock - DEBUG - Lock acquired: account_lock:21610093
2025-06-09 17:23:01,848 - app.services.distributed_lock - ERROR - Error during locked operation for account 21610093: __aenter__
2025-06-09 17:23:01,852 - app.core.rollback_manager - ERROR - Transaction failed: strategy_execution - __aenter__
```

### Stack Trace Analysis
The `__aenter__` error suggests that an async context manager is not being properly awaited or initialized. This typically happens when:
1. Async context manager used in sync context
2. Context manager receives wrong type of object
3. Database session type mismatch prevents proper initialization

## Success Criteria

### When Integration is Complete
- [ ] Webhook execution uses full async infrastructure
- [ ] No `__aenter__` errors in logs
- [ ] Transaction rollback works correctly
- [ ] Distributed locking prevents race conditions
- [ ] Circuit breaker protects against cascading failures
- [ ] Performance is maintained or improved
- [ ] All existing functionality preserved

### Performance Benchmarks
- **Current Direct Execution**: ~270ms average
- **Target Async Execution**: <300ms average
- **Concurrent Execution**: Support 10+ simultaneous webhooks
- **Error Recovery**: Automatic rollback within 5 seconds

## Priority Actions

### Immediate (High Priority)
1. **Analyze rollback_manager.py** - Understand async context manager implementation
2. **Review distributed_lock.py** - Check session type requirements
3. **Test AsyncSession compatibility** - Verify context managers work with AsyncSession

### Medium Priority
1. **Create async-compatible StrategyProcessor** - Full async database operations
2. **Implement comprehensive testing** - Unit and integration tests
3. **Performance optimization** - Ensure async doesn't degrade performance

### Low Priority
1. **Documentation updates** - Update architecture docs
2. **Monitoring improvements** - Better async operation tracking
3. **Cleanup temporary workaround** - Remove direct execution path when async works

## Conclusion

The async infrastructure provides important production benefits (transaction safety, race condition prevention, failure protection) but requires proper session type integration. The current direct execution workaround proves the core trading logic works, but production deployment should use the full async infrastructure for reliability and robustness.

The main challenge is ensuring all async context managers work correctly with AsyncSession and that the entire execution chain maintains async compatibility throughout.