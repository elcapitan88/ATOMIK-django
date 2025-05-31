# app/services/chat_service.py
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Optional

from app.models.chat import ChatChannel, UserChatRole, ChatChannelMember
from app.models.user import User
from app.models.subscription import Subscription
from .chat_role_service import (
    assign_default_role_from_subscription,
    get_user_role_color,
    sync_user_subscription_role
)


def initialize_default_channels(db: Session):
    """Initialize default chat channels if they don't exist"""
    default_channels = [
        {
            "name": "general",
            "description": "General discussion for all members",
            "is_general": True,
            "sort_order": 1
        },
        {
            "name": "trading-signals",
            "description": "Trading signals and market discussion",
            "is_general": False,
            "sort_order": 2
        },
        {
            "name": "strategy-discussion",
            "description": "Discuss trading strategies",
            "is_general": False,
            "sort_order": 3
        },
        {
            "name": "announcements",
            "description": "Important platform announcements",
            "is_general": False,
            "sort_order": 4
        }
    ]
    
    for channel_data in default_channels:
        existing = db.query(ChatChannel).filter(
            ChatChannel.name == channel_data["name"]
        ).first()
        
        if not existing:
            new_channel = ChatChannel(**channel_data)
            db.add(new_channel)
    
    db.commit()


async def assign_default_role_based_on_subscription(user_id: int, db: Session):
    """Assign a default chat role based on user's subscription tier"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return
    
    # Use the new role service
    await assign_default_role_from_subscription(db, user_id)


def ensure_user_in_general_channel(user_id: int, db: Session):
    """Ensure user is a member of the general channel"""
    general_channel = db.query(ChatChannel).filter(
        and_(
            ChatChannel.name == "general",
            ChatChannel.is_active == True
        )
    ).first()
    
    if not general_channel:
        return
    
    # Check if user is already a member
    existing_member = db.query(ChatChannelMember).filter(
        and_(
            ChatChannelMember.channel_id == general_channel.id,
            ChatChannelMember.user_id == user_id
        )
    ).first()
    
    if not existing_member:
        new_member = ChatChannelMember(
            channel_id=general_channel.id,
            user_id=user_id
        )
        db.add(new_member)
        db.commit()


async def setup_user_for_chat(user_id: int, db: Session):
    """Complete setup for a user to use chat (role + general channel membership)"""
    await assign_default_role_based_on_subscription(user_id, db)
    ensure_user_in_general_channel(user_id, db)


async def update_user_role_from_subscription(user_id: int, new_tier: str, db: Session):
    """Update user's chat role when their subscription changes"""
    # Use the new role service
    await sync_user_subscription_role(db, user_id)