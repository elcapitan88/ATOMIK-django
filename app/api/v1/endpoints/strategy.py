from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Union, Optional, Dict, Any
import logging
import traceback
from pydantic import ValidationError
from app.core.config import settings
from decimal import Decimal

from app.core.security import get_current_user
from app.services.strategy_service import StrategyProcessor
from app.db.session import get_db
from app.models.strategy import ActivatedStrategy, strategy_follower_quantities 
from app.models.webhook import Webhook, WebhookSubscription
from app.models.broker import BrokerAccount
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

@router.post("/{strategy_id}/execute")
async def execute_strategy_manually(
    strategy_id: int,
    action_data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Execute a strategy manually from the UI"""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Create signal data from action
        signal_data = {
            "action": action_data["action"],
            "order_type": "MARKET",
            "time_in_force": "GTC"
        }
        
        # Use existing strategy processor
        strategy_processor = StrategyProcessor(db)
        result = await strategy_processor.execute_strategy(strategy, signal_data)
        
        return result
    except Exception as e:
        logger.error(f"Manual strategy execution error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute strategy: {str(e)}"
        )

@router.post("/activate", response_model=StrategyResponse)
async def activate_strategy(
    *,
    db: Session = Depends(get_db),
    strategy: Union[SingleStrategyCreate, MultipleStrategyCreate],
    current_user = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None)
):
    try:
        logger.info(f"Creating strategy for user {current_user.id}")
        logger.debug(f"Strategy data received: {strategy.dict()}")

        # Updated webhook validation to support subscriptions
        webhook = db.query(Webhook).filter(
            Webhook.token == str(strategy.webhook_id)
        ).first()

        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")

        # Check if user owns or is subscribed to the webhook
        is_owner = webhook.user_id == current_user.id
        is_subscriber = db.query(WebhookSubscription).filter(
            WebhookSubscription.webhook_id == webhook.id,
            WebhookSubscription.user_id == current_user.id
        ).first() is not None

        if not (is_owner or is_subscriber):
            raise HTTPException(
                status_code=403,
                detail="You don't have access to this webhook"
            )

        try:
            if isinstance(strategy, SingleStrategyCreate):
                logger.info("Processing single account strategy")
                
                # Validate broker account
                broker_account = db.query(BrokerAccount).filter(
                    BrokerAccount.account_id == str(strategy.account_id),
                    BrokerAccount.user_id == current_user.id,
                    BrokerAccount.is_active == True
                ).first()
                
                if not broker_account:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Broker account {strategy.account_id} not found or inactive"
                    )

                # Check for existing strategy with same webhook and account
                existing_strategy = db.query(ActivatedStrategy).filter(
                    ActivatedStrategy.webhook_id == str(strategy.webhook_id),
                    ActivatedStrategy.account_id == str(strategy.account_id),
                    ActivatedStrategy.user_id == current_user.id
                ).first()

                if existing_strategy:
                    raise HTTPException(
                        status_code=400,
                        detail="A strategy with this webhook and account already exists"
                    )
                
                # Create single account strategy
                db_strategy = ActivatedStrategy(
                    user_id=current_user.id,
                    strategy_type="single",
                    webhook_id=str(strategy.webhook_id),
                    ticker=strategy.ticker,
                    account_id=str(strategy.account_id),
                    quantity=strategy.quantity,
                    is_active=True
                )
                
                db.add(db_strategy)
                db.flush()

                logger.debug(f"Created strategy object with ID: {db_strategy.id}")

                # Create empty stats for new strategy
                stats = StrategyStats.create_empty()
                
                # Prepare response data
                strategy_data = {
                    "id": db_strategy.id,
                    "strategy_type": db_strategy.strategy_type,
                    "webhook_id": db_strategy.webhook_id,
                    "ticker": db_strategy.ticker,
                    "is_active": db_strategy.is_active,
                    "created_at": db_strategy.created_at,
                    "last_triggered": db_strategy.last_triggered,
                    "account_id": broker_account.account_id,
                    "quantity": db_strategy.quantity,
                    "broker_account": {
                        "account_id": broker_account.account_id,
                        "name": broker_account.name,
                        "broker_id": broker_account.broker_id
                    },
                    "webhook": {
                        "name": webhook.name,
                        "source_type": webhook.source_type
                    },
                    "stats": stats.to_summary_dict()
                }

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

                # Validate follower accounts
                if len(strategy.follower_account_ids) != len(strategy.follower_quantities):
                    raise HTTPException(
                        status_code=400,
                        detail="Number of follower accounts must match number of quantities"
                    )

                follower_accounts = []
                existing_account_ids = {leader_account.account_id}

                for follower_id in strategy.follower_account_ids:
                    if follower_id in existing_account_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Duplicate account ID: {follower_id}"
                        )
                    existing_account_ids.add(follower_id)

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

                    follower_accounts.append(follower)

                # Create multiple account strategy
                db_strategy = ActivatedStrategy(
                    user_id=current_user.id,
                    strategy_type="multiple",
                    webhook_id=str(strategy.webhook_id),
                    ticker=strategy.ticker,
                    leader_account_id=leader_account.account_id,
                    leader_quantity=strategy.leader_quantity,
                    group_name=strategy.group_name,
                    is_active=True
                )

                db.add(db_strategy)
                db.flush()

                # Add follower relationships
                for idx, follower in enumerate(follower_accounts):
                    db.execute(
                        strategy_follower_quantities.insert().values(
                            strategy_id=db_strategy.id,
                            account_id=follower.account_id,
                            quantity=strategy.follower_quantities[idx]
                        )
                    )

                stats = StrategyStats.create_empty()

                # Prepare response data for multiple strategy
                strategy_data = {
                    "id": db_strategy.id,
                    "strategy_type": db_strategy.strategy_type,
                    "webhook_id": db_strategy.webhook_id,
                    "ticker": db_strategy.ticker,
                    "is_active": db_strategy.is_active,
                    "created_at": db_strategy.created_at,
                    "last_triggered": db_strategy.last_triggered,
                    "group_name": db_strategy.group_name,
                    "leader_account_id": leader_account.account_id,
                    "leader_quantity": db_strategy.leader_quantity,
                    "leader_broker_account": {
                        "account_id": leader_account.account_id,
                        "name": leader_account.name,
                        "broker_id": leader_account.broker_id
                    },
                    "follower_accounts": [
                        {
                            "account_id": acc.account_id,
                            "quantity": strategy.follower_quantities[idx]
                        }
                        for idx, acc in enumerate(follower_accounts)
                    ],
                    "webhook": {
                        "name": webhook.name,
                        "source_type": webhook.source_type
                    },
                    "stats": stats.to_summary_dict()
                }

            db.commit()
            logger.info(f"Successfully created strategy with ID: {db_strategy.id}")
            
            return StrategyResponse(**strategy_data)

        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Database error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error creating strategy: {str(e)}"
            )

    except ValidationError as ve:
        logger.error(f"Validation error: {str(ve)}")
        raise HTTPException(
            status_code=422,
            detail=str(ve)
        )
    except HTTPException as he:
        logger.error(f"HTTP Exception in activate_strategy: {he.status_code}: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"Error activating strategy: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to activate strategy: {str(e)}"
        )
    
@router.get("/list", response_model=List[StrategyResponse])
async def list_strategies(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        logger.info(f"Fetching strategies for user {current_user.id}")
        
        strategies = (
            db.query(ActivatedStrategy)
            .filter(ActivatedStrategy.user_id == current_user.id)
            .options(
                joinedload(ActivatedStrategy.broker_account),
                joinedload(ActivatedStrategy.leader_broker_account),
                joinedload(ActivatedStrategy.webhook)
            )
            .all()
        )

        response_strategies = []
        for strategy in strategies:
            try:
                strategy_data = {
                    "id": strategy.id,
                    "strategy_type": strategy.strategy_type,
                    "webhook_id": strategy.webhook_id,
                    "ticker": strategy.ticker,
                    "is_active": strategy.is_active,
                    "created_at": strategy.created_at,
                    "last_triggered": strategy.last_triggered,
                    "webhook": {
                        "name": strategy.webhook.name if strategy.webhook else None,
                        "source_type": strategy.webhook.source_type if strategy.webhook else "custom"
                    }
                }

                if strategy.strategy_type == "single":
                    # Add single strategy specific fields
                    strategy_data.update({
                        "account_id": strategy.account_id,  # Add this line
                        "quantity": strategy.quantity,      # Add this line
                        "broker_account": {
                            "account_id": strategy.broker_account.account_id,
                            "name": strategy.broker_account.name,
                            "broker_id": strategy.broker_account.broker_id
                        } if strategy.broker_account else None,
                        "leader_account_id": None,
                        "leader_quantity": None,
                        "leader_broker_account": None,
                        "follower_accounts": [],
                        "group_name": None
                    })
                else:
                    # Multiple strategy fields remain the same
                    strategy_data.update({
                        "group_name": strategy.group_name,
                        "leader_account_id": strategy.leader_account_id,
                        "leader_quantity": strategy.leader_quantity,
                        "leader_broker_account": {
                            "account_id": strategy.leader_broker_account.account_id,
                            "name": strategy.leader_broker_account.name,
                            "broker_id": strategy.leader_broker_account.broker_id
                        } if strategy.leader_broker_account else None,
                        "follower_accounts": strategy.get_follower_accounts(),
                        "account_id": None,
                        "quantity": None
                    })

                # Add stats
                strategy_data["stats"] = {
                    "total_trades": strategy.total_trades,
                    "successful_trades": strategy.successful_trades,
                    "failed_trades": strategy.failed_trades,
                    "total_pnl": float(strategy.total_pnl) if strategy.total_pnl else 0,
                    "win_rate": float(strategy.win_rate) if strategy.win_rate else None,
                    "average_trade_pnl": None  # Add calculation if needed
                }

                response_strategies.append(strategy_data)

            except Exception as strategy_error:
                logger.error(f"Error processing strategy {strategy.id}: {str(strategy_error)}")
                continue

        return response_strategies

    except Exception as e:
        logger.error(f"Error in list_strategies: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while fetching strategies"
        )

@router.post("/{strategy_id}/toggle")
async def toggle_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Toggle the active status
        strategy.is_active = not strategy.is_active
        db.commit()
        db.refresh(strategy)
        
        # Return the complete strategy object
        return strategy
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to toggle strategy: {str(e)}"
        )

@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete a strategy"""
    try:
        # Get the strategy
        strategy = (
            db.query(ActivatedStrategy)
            .filter(
                ActivatedStrategy.id == strategy_id,
                ActivatedStrategy.user_id == current_user.id
            )
            .first()
        )
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Only delete this specific strategy
        db.delete(strategy)
        db.commit()
        
        return {"status": "success", "message": "Strategy deleted successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete strategy: {str(e)}"
        )