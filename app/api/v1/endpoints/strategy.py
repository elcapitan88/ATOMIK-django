from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Union
import logging
from app.core.config import settings
from decimal import Decimal

from app.core.security import get_current_user
from app.core.permissions import check_subscription_feature
from app.db.session import get_db
from app.models.strategy import ActivatedStrategy
from app.models.webhook import Webhook
from app.models.broker import BrokerAccount
from app.models.subscription import SubscriptionTier
from app.schemas.strategy import (
    SingleStrategyCreate,
    MultipleStrategyCreate,
    StrategyUpdate,
    StrategyInDB,
    StrategyResponse,
    StrategyType,
    StrategyStats
)

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/activate", response_model=StrategyResponse)
@check_subscription_feature(SubscriptionTier.STARTED)
async def activate_strategy(
    *,
    db: Session = Depends(get_db),
    strategy: Union[SingleStrategyCreate, MultipleStrategyCreate],
    current_user = Depends(get_current_user)
):
    """Activate a new trading strategy"""
    try:
        logger.info(f"Creating strategy for user {current_user.id}")

        # If subscription checks are skipped, we won't do any tier-based checks
        if not settings.SKIP_SUBSCRIPTION_CHECK:
            if not current_user.subscription:
                raise HTTPException(status_code=403, detail="No active subscription found")

            # Check if multiple account strategy is allowed
            if (isinstance(strategy, MultipleStrategyCreate) and 
                current_user.subscription.tier == SubscriptionTier.STARTED):
                raise HTTPException(
                    status_code=403,
                    detail="Multiple account strategies require Plus subscription or higher"
                )

            # Check strategy limits based on subscription tier
            existing_strategies = db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == current_user.id,
                ActivatedStrategy.is_active == True
            ).count()

            strategy_limits = {
                SubscriptionTier.STARTED: 1,
                SubscriptionTier.PLUS: float('inf'),
                SubscriptionTier.PRO: float('inf'),
                SubscriptionTier.LIFETIME: float('inf')
            }

            limit = strategy_limits.get(current_user.subscription.tier, 0)
            if existing_strategies >= limit:
                raise HTTPException(
                    status_code=403,
                    detail=f"Strategy limit reached for your subscription tier"
                )

        # Find webhook by token and user
        webhook = db.query(Webhook).filter(
            Webhook.token == str(strategy.webhook_id),
            Webhook.user_id == current_user.id
        ).first()

        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")

        # Convert webhook_id to string and add user_id
        strategy_data = strategy.dict()
        strategy_data['webhook_id'] = str(strategy_data['webhook_id'])
        strategy_data['user_id'] = current_user.id

        # Create new strategy
        db_strategy = ActivatedStrategy(**strategy_data)
        db.add(db_strategy)
        
        # For multiple strategy, add follower accounts
        if isinstance(strategy, MultipleStrategyCreate):
            for account_id in strategy.follower_account_ids:
                account = db.query(BrokerAccount).filter(
                    BrokerAccount.account_id == account_id
                ).first()
                
                if account:
                    db_strategy.follower_accounts.append(account)
        
        db.commit()
        db.refresh(db_strategy)

        # Create response with proper structure
        response = StrategyResponse(
            id=db_strategy.id,
            strategy_type=db_strategy.strategy_type,
            webhook_id=db_strategy.webhook_id,
            ticker=db_strategy.ticker,
            is_active=db_strategy.is_active,
            created_at=db_strategy.created_at,
            last_triggered=db_strategy.last_triggered,
            stats=StrategyStats(
                total_trades=0,
                successful_trades=0,
                failed_trades=0,
                total_pnl=Decimal('0.00')
            )
        )

        if db_strategy.strategy_type == "single":
            response.account_id = db_strategy.account_id
            response.quantity = db_strategy.quantity
        else:
            response.leader_account_id = db_strategy.leader_account_id
            response.leader_quantity = db_strategy.leader_quantity
            response.follower_quantity = db_strategy.follower_quantity
            response.group_name = db_strategy.group_name
            response.follower_account_ids = [acc.account_id for acc in db_strategy.follower_accounts]

        logger.info(f"Created strategy with ID: {db_strategy.id}")
        return response

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error activating strategy: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to activate strategy: {str(e)}"
        )

@router.get("/list", response_model=List[StrategyResponse])
@check_subscription_feature(SubscriptionTier.STARTED)
async def list_strategies(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List all strategies for the current user"""
    try:
        strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.user_id == current_user.id,
            ActivatedStrategy.is_active == True, 
        ).all()
        
        logger.info(f"Found {len(strategies)} active strategies for user {current_user.id}")

        response_strategies = []
        for db_strategy in strategies:
            response = StrategyResponse(
                id=db_strategy.id,
                strategy_type=db_strategy.strategy_type,
                webhook_id=db_strategy.webhook_id,
                ticker=db_strategy.ticker,
                is_active=db_strategy.is_active,
                created_at=db_strategy.created_at,
                last_triggered=db_strategy.last_triggered,
                stats=StrategyStats(
                    total_trades=db_strategy.total_trades,
                    successful_trades=db_strategy.successful_trades,
                    failed_trades=db_strategy.failed_trades,
                    total_pnl=Decimal('0.00')
                )
            )
            
            if db_strategy.strategy_type == "single":
                response.account_id = db_strategy.account_id
                response.quantity = db_strategy.quantity
            else:
                response.leader_account_id = db_strategy.leader_account_id
                response.leader_quantity = db_strategy.leader_quantity
                response.follower_quantity = db_strategy.follower_quantity
                response.group_name = db_strategy.group_name
                response.follower_account_ids = [acc.account_id for acc in db_strategy.follower_accounts]
            
            response_strategies.append(response)
        
        return response_strategies
        
    except Exception as e:
        logger.error(f"Error listing strategies: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list strategies: {str(e)}"
        )

@router.post("/{strategy_id}/toggle", response_model=StrategyInDB)
@check_subscription_feature(SubscriptionTier.STARTED)
async def toggle_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Toggle a strategy's active status"""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        strategy.is_active = not strategy.is_active
        db.commit()
        db.refresh(strategy)
        
        return strategy
    except Exception as e:
        logger.error(f"Error toggling strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to toggle strategy: {str(e)}"
        )

@router.delete("/{strategy_id}")
@check_subscription_feature(SubscriptionTier.STARTED)
async def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete a strategy"""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        db.delete(strategy)
        db.commit()
        
        return {"status": "success", "message": "Strategy deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete strategy: {str(e)}"
        )