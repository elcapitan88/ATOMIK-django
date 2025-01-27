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
        logger.debug(f"Strategy data received: {strategy.dict()}")

        # Subscription validation
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

        # Find and validate webhook
        webhook = db.query(Webhook).filter(
            Webhook.token == str(strategy.webhook_id),
            Webhook.user_id == current_user.id
        ).first()

        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")

        if isinstance(strategy, SingleStrategyCreate):
            logger.info("Processing single account strategy")
            
            # Validate broker account
            broker_account = db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.account_id,
                BrokerAccount.user_id == current_user.id,
                BrokerAccount.is_active == True
            ).first()
            
            if not broker_account:
                raise HTTPException(
                    status_code=404,
                    detail=f"Broker account {strategy.account_id} not found or inactive"
                )
            
            # Create single account strategy
            db_strategy = ActivatedStrategy(
                user_id=current_user.id,
                strategy_type="single",
                webhook_id=str(strategy.webhook_id),
                ticker=strategy.ticker,
                account_id=broker_account.id,
                quantity=strategy.quantity,
                is_active=True
            )
            
        else:  # MultipleStrategyCreate
            logger.info("Processing multiple account strategy")
            
            # Validate leader account
            leader_account = db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.leader_account_id,
                BrokerAccount.user_id == current_user.id,
                BrokerAccount.is_active == True
            ).first()
            
            if not leader_account:
                raise HTTPException(
                    status_code=404,
                    detail=f"Leader account {strategy.leader_account_id} not found or inactive"
                )

            # Validate follower accounts and collect data
            follower_data = []
            existing_account_ids = set()
            
            # Validate length match between accounts and quantities
            if len(strategy.follower_account_ids) != len(strategy.follower_quantities):
                raise HTTPException(
                    status_code=400,
                    detail="Number of follower accounts must match number of quantities"
                )
            
            for idx, follower_id in enumerate(strategy.follower_account_ids):
                # Check for duplicate accounts
                if follower_id in existing_account_ids:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Duplicate follower account: {follower_id}"
                    )
                existing_account_ids.add(follower_id)
                
                # Validate each follower account
                follower = db.query(BrokerAccount).filter(
                    BrokerAccount.account_id == follower_id,
                    BrokerAccount.user_id == current_user.id,
                    BrokerAccount.is_active == True
                ).first()
                
                if not follower:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Follower account {follower_id} not found or inactive"
                    )
                
                if follower.id == leader_account.id:
                    raise HTTPException(
                        status_code=400,
                        detail="Leader account cannot be a follower"
                    )
                
                quantity = strategy.follower_quantities[idx]
                if quantity <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid quantity for follower {follower_id}: {quantity}"
                    )
                
                follower_data.append({
                    'account': follower,
                    'quantity': quantity
                })

            # Create multiple account strategy
            db_strategy = ActivatedStrategy(
                user_id=current_user.id,
                strategy_type="multiple",
                webhook_id=str(strategy.webhook_id),
                ticker=strategy.ticker,
                leader_account_id=leader_account.id,
                leader_quantity=strategy.leader_quantity,
                group_name=strategy.group_name,
                is_active=True
            )
            
            db.add(db_strategy)
            db.flush()  # Get the strategy ID
            
            # Add followers with their quantities
            for data in follower_data:
                stmt = strategy_follower_quantities.insert().values(
                    strategy_id=db_strategy.id,
                    account_id=data['account'].id,
                    quantity=data['quantity']
                )
                db.execute(stmt)

        db.add(db_strategy)
        db.commit()
        db.refresh(db_strategy)
        
        # Prepare response data
        response_data = {
            "id": db_strategy.id,
            "strategy_type": db_strategy.strategy_type,
            "webhook_id": db_strategy.webhook_id,
            "ticker": db_strategy.ticker,
            "is_active": db_strategy.is_active,
            "created_at": db_strategy.created_at,
            "last_triggered": db_strategy.last_triggered,
            "stats": StrategyStats(
                total_trades=0,
                successful_trades=0,
                failed_trades=0,
                total_pnl=Decimal('0.00')
            )
        }
        
        if db_strategy.strategy_type == "single":
            response_data.update({
                "account_id": strategy.account_id,
                "quantity": db_strategy.quantity
            })
        else:
            response_data.update({
                "leader_account_id": strategy.leader_account_id,
                "leader_quantity": db_strategy.leader_quantity,
                "group_name": db_strategy.group_name,
                "follower_account_ids": strategy.follower_account_ids,
                "follower_quantities": strategy.follower_quantities
            })

        logger.info(f"Successfully created strategy with ID: {db_strategy.id}")
        return StrategyResponse(**response_data)

    except HTTPException as he:
        logger.error(f"HTTP Exception in activate_strategy: {str(he)}")
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