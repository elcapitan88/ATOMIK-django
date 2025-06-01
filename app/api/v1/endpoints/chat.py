# app/api/v1/endpoints/chat.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from typing import List, Optional
from datetime import datetime

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.chat import (
    ChatChannel, 
    ChatMessage, 
    ChatReaction, 
    UserChatRole, 
    UserChatSettings,
    ChatChannelMember
)
from app.schemas.chat import (
    ChatChannel as ChatChannelSchema,
    ChatChannelCreate,
    ChatChannelUpdate,
    ChatMessage as ChatMessageSchema,
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatReactionCreate,
    ChatReaction as ChatReactionSchema,
    UserChatSettings as UserChatSettingsSchema,
    UserChatSettingsUpdate,
    ChatMessageList,
    ChatChannelWithUnreadCount,
    UserWithRole
)
from .chat_sse import (
    broadcast_new_message,
    broadcast_message_updated,
    broadcast_message_deleted,
    broadcast_reaction_added,
    broadcast_reaction_removed
)
from app.services.chat_role_service import (
    assign_admin_role,
    assign_moderator_role,
    assign_vip_role,
    assign_beta_tester_role,
    remove_admin_role,
    remove_moderator_role,
    remove_vip_role,
    remove_beta_tester_role,
    get_user_roles,
    get_user_primary_role,
    is_user_admin,
    is_user_moderator,
    is_user_beta_tester,
    is_user_staff,
    get_all_admins,
    get_all_moderators,
    get_all_beta_testers,
    sync_user_subscription_role,
    sync_existing_beta_testers
)
from app.services.chat_service import initialize_default_channels
from app.services.feature_flag_service import require_member_chat

router = APIRouter()


# Channel Management
@router.get("/channels", response_model=List[ChatChannelWithUnreadCount])
@require_member_chat
async def get_channels(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all active channels with unread message counts for the current user"""
    # Get all active channels
    channels = db.query(ChatChannel).filter(
        ChatChannel.is_active == True
    ).order_by(ChatChannel.sort_order).all()
    
    result = []
    for channel in channels:
        # Get unread count for this user
        member = db.query(ChatChannelMember).filter(
            and_(
                ChatChannelMember.channel_id == channel.id,
                ChatChannelMember.user_id == current_user.id
            )
        ).first()
        
        if member:
            unread_count = db.query(func.count(ChatMessage.id)).filter(
                and_(
                    ChatMessage.channel_id == channel.id,
                    ChatMessage.created_at > member.last_read_at,
                    ChatMessage.is_deleted == False
                )
            ).scalar()
        else:
            # User hasn't joined channel yet, count all messages
            unread_count = db.query(func.count(ChatMessage.id)).filter(
                and_(
                    ChatMessage.channel_id == channel.id,
                    ChatMessage.is_deleted == False
                )
            ).scalar()
        
        # Convert to schema and add unread count
        channel_data = ChatChannelSchema.from_orm(channel)
        channel_with_unread = ChatChannelWithUnreadCount(
            **channel_data.dict(),
            unread_count=unread_count or 0
        )
        result.append(channel_with_unread)
    
    return result


@router.post("/channels", response_model=ChatChannelSchema)
async def create_channel(
    channel_data: ChatChannelCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new chat channel (admin only for now)"""
    # TODO: Add admin permission check
    if not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can create channels")
    
    # Check if channel name already exists
    existing = db.query(ChatChannel).filter(ChatChannel.name == channel_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Channel name already exists")
    
    # Create new channel
    new_channel = ChatChannel(
        **channel_data.dict(),
        created_by=current_user.id
    )
    
    db.add(new_channel)
    db.commit()
    db.refresh(new_channel)
    
    return new_channel


@router.put("/channels/{channel_id}", response_model=ChatChannelSchema)
async def update_channel(
    channel_id: int,
    channel_data: ChatChannelUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a chat channel (admin only)"""
    if not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can update channels")
    
    channel = db.query(ChatChannel).filter(ChatChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Update fields
    update_data = channel_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(channel, field, value)
    
    channel.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(channel)
    
    return channel


# Message Management
@router.get("/channels/{channel_id}/messages", response_model=ChatMessageList)
@require_member_chat
async def get_channel_messages(
    channel_id: int,
    limit: int = Query(50, ge=1, le=100),
    before: Optional[int] = Query(None, description="Message ID to load messages before"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get messages from a channel with pagination"""
    # Verify channel exists and is active
    channel = db.query(ChatChannel).filter(
        and_(ChatChannel.id == channel_id, ChatChannel.is_active == True)
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Build query
    query = db.query(ChatMessage).filter(
        and_(
            ChatMessage.channel_id == channel_id,
            ChatMessage.is_deleted == False
        )
    )
    
    if before:
        query = query.filter(ChatMessage.id < before)
    
    # Get messages with user and role information
    messages = query.order_by(desc(ChatMessage.created_at)).limit(limit + 1).all()
    
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:-1]  # Remove the extra message used for has_more detection
    
    # Get user roles for all message authors
    user_ids = [msg.user_id for msg in messages]
    user_roles = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id.in_(user_ids),
            UserChatRole.is_active == True
        )
    ).all()
    
    # Create mapping of user_id to highest priority role
    role_map = {}
    for role in user_roles:
        if role.user_id not in role_map or role.role_priority > role_map[role.user_id].role_priority:
            role_map[role.user_id] = role
    
    # Get user details (username and profile picture)
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    username_map = {user.id: user.username for user in users}
    profile_pic_map = {user.id: user.profile_picture for user in users}
    
    # Build response with reactions
    result_messages = []
    for message in reversed(messages):  # Reverse to show oldest first
        # Get reactions for this message
        reactions = db.query(ChatReaction).filter(
            ChatReaction.message_id == message.id
        ).all()
        
        # Group reactions by emoji
        reaction_summary = {}
        for reaction in reactions:
            emoji = reaction.emoji
            if emoji not in reaction_summary:
                reaction_summary[emoji] = {
                    'emoji': emoji,
                    'count': 0,
                    'users': []
                }
            reaction_summary[emoji]['count'] += 1
            reaction_summary[emoji]['users'].append(username_map.get(reaction.user_id, 'Unknown'))
        
        # Get user role color
        user_role = role_map.get(message.user_id)
        role_color = user_role.role_color if user_role else '#FFFFFF'
        
        # Create message schema
        message_data = ChatMessageSchema(
            id=message.id,
            channel_id=message.channel_id,
            user_id=message.user_id,
            user_name=username_map.get(message.user_id, 'Unknown'),
            user_role_color=role_color,
            user_profile_picture=profile_pic_map.get(message.user_id),
            content=message.content,
            reply_to_id=message.reply_to_id,
            is_edited=message.is_edited,
            edited_at=message.edited_at,
            created_at=message.created_at,
            is_deleted=message.is_deleted,
            reactions=list(reaction_summary.values())
        )
        result_messages.append(message_data)
    
    # Update user's last read timestamp for this channel
    member = db.query(ChatChannelMember).filter(
        and_(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == current_user.id
        )
    ).first()
    
    if member:
        member.last_read_at = datetime.utcnow()
    else:
        # Add user to channel if they're not already a member
        new_member = ChatChannelMember(
            channel_id=channel_id,
            user_id=current_user.id,
            last_read_at=datetime.utcnow()
        )
        db.add(new_member)
    
    db.commit()
    
    return ChatMessageList(
        messages=result_messages,
        total_count=len(result_messages),
        has_more=has_more
    )


@router.post("/channels/{channel_id}/messages", response_model=ChatMessageSchema)
@require_member_chat
async def send_message(
    channel_id: int,
    message_data: ChatMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send a new message to a channel"""
    # Verify channel exists and is active
    channel = db.query(ChatChannel).filter(
        and_(ChatChannel.id == channel_id, ChatChannel.is_active == True)
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Verify reply_to message exists if specified
    if message_data.reply_to_id:
        reply_to = db.query(ChatMessage).filter(
            and_(
                ChatMessage.id == message_data.reply_to_id,
                ChatMessage.channel_id == channel_id,
                ChatMessage.is_deleted == False
            )
        ).first()
        if not reply_to:
            raise HTTPException(status_code=400, detail="Reply target message not found")
    
    # Create new message
    new_message = ChatMessage(
        channel_id=channel_id,
        user_id=current_user.id,
        content=message_data.content,
        reply_to_id=message_data.reply_to_id
    )
    
    db.add(new_message)
    db.commit()
    db.refresh(new_message)
    
    # Get user role for response
    user_role = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == current_user.id,
            UserChatRole.is_active == True
        )
    ).order_by(desc(UserChatRole.role_priority)).first()
    
    role_color = user_role.role_color if user_role else '#FFFFFF'
    
    # Ensure user is a member of the channel
    member = db.query(ChatChannelMember).filter(
        and_(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == current_user.id
        )
    ).first()
    
    if not member:
        new_member = ChatChannelMember(
            channel_id=channel_id,
            user_id=current_user.id,
            last_read_at=datetime.utcnow()
        )
        db.add(new_member)
        db.commit()
    
    # Broadcast the new message to all connected users
    await broadcast_new_message(
        message=new_message, 
        user_name=current_user.username, 
        user_role_color=role_color, 
        user_profile_picture=current_user.profile_picture, 
        db=db
    )
    
    return ChatMessageSchema(
        id=new_message.id,
        channel_id=new_message.channel_id,
        user_id=new_message.user_id,
        user_name=current_user.username,
        user_role_color=role_color,
        user_profile_picture=current_user.profile_picture,
        content=new_message.content,
        reply_to_id=new_message.reply_to_id,
        is_edited=new_message.is_edited,
        edited_at=new_message.edited_at,
        created_at=new_message.created_at,
        is_deleted=new_message.is_deleted,
        reactions=[]
    )


@router.put("/messages/{message_id}", response_model=ChatMessageSchema)
async def edit_message(
    message_id: int,
    message_data: ChatMessageUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Edit a message (only by the message author)"""
    # Get the message
    message = db.query(ChatMessage).filter(
        and_(
            ChatMessage.id == message_id,
            ChatMessage.is_deleted == False
        )
    ).first()
    
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Check if user is the author
    if message.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own messages")
    
    # Store original content if this is the first edit
    if not message.is_edited:
        message.original_content = message.content
    
    # Update message
    message.content = message_data.content
    message.is_edited = True
    message.edited_at = datetime.utcnow()
    
    db.commit()
    db.refresh(message)
    
    # Get user role for response
    user_role = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == current_user.id,
            UserChatRole.is_active == True
        )
    ).order_by(desc(UserChatRole.role_priority)).first()
    
    role_color = user_role.role_color if user_role else '#FFFFFF'
    
    # Broadcast the message update
    await broadcast_message_updated(message, current_user.username, role_color, current_user.profile_picture, db)
    
    return ChatMessageSchema(
        id=message.id,
        channel_id=message.channel_id,
        user_id=message.user_id,
        user_name=current_user.username,
        user_role_color=role_color,
        user_profile_picture=current_user.profile_picture,
        content=message.content,
        reply_to_id=message.reply_to_id,
        is_edited=message.is_edited,
        edited_at=message.edited_at,
        created_at=message.created_at,
        is_deleted=message.is_deleted,
        reactions=[]
    )


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a message (by author or admin)"""
    # Get the message
    message = db.query(ChatMessage).filter(
        and_(
            ChatMessage.id == message_id,
            ChatMessage.is_deleted == False
        )
    ).first()
    
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Check if user is the author or an admin
    if message.user_id != current_user.id and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    
    # Soft delete the message
    message.is_deleted = True
    message.deleted_at = datetime.utcnow()
    
    db.commit()
    
    # Broadcast the message deletion
    await broadcast_message_deleted(message_id, message.channel_id, db)
    
    return {"detail": "Message deleted successfully"}


# Reaction Management
@router.post("/messages/{message_id}/reactions", response_model=ChatReactionSchema)
async def add_reaction(
    message_id: int,
    reaction_data: ChatReactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a reaction to a message"""
    # Verify message exists and is not deleted
    message = db.query(ChatMessage).filter(
        and_(
            ChatMessage.id == message_id,
            ChatMessage.is_deleted == False
        )
    ).first()
    
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Check if user already reacted with this emoji
    existing_reaction = db.query(ChatReaction).filter(
        and_(
            ChatReaction.message_id == message_id,
            ChatReaction.user_id == current_user.id,
            ChatReaction.emoji == reaction_data.emoji
        )
    ).first()
    
    if existing_reaction:
        raise HTTPException(status_code=400, detail="You have already reacted with this emoji")
    
    # Create new reaction
    new_reaction = ChatReaction(
        message_id=message_id,
        user_id=current_user.id,
        emoji=reaction_data.emoji
    )
    
    db.add(new_reaction)
    db.commit()
    db.refresh(new_reaction)
    
    # Broadcast the reaction addition
    await broadcast_reaction_added(new_reaction, current_user.username, db)
    
    return new_reaction


@router.delete("/messages/{message_id}/reactions/{emoji}")
async def remove_reaction(
    message_id: int,
    emoji: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a reaction from a message"""
    # Find the reaction
    reaction = db.query(ChatReaction).filter(
        and_(
            ChatReaction.message_id == message_id,
            ChatReaction.user_id == current_user.id,
            ChatReaction.emoji == emoji
        )
    ).first()
    
    if not reaction:
        raise HTTPException(status_code=404, detail="Reaction not found")
    
    # Store message_id before deletion
    message_id = reaction.message_id
    
    db.delete(reaction)
    db.commit()
    
    # Broadcast the reaction removal
    await broadcast_reaction_removed(message_id, current_user.id, emoji, current_user.username, db)
    
    return {"detail": "Reaction removed successfully"}


# User Settings
@router.get("/settings", response_model=UserChatSettingsSchema)
async def get_chat_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's chat settings"""
    settings = db.query(UserChatSettings).filter(
        UserChatSettings.user_id == current_user.id
    ).first()
    
    if not settings:
        # Create default settings
        settings = UserChatSettings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    return settings


@router.put("/settings", response_model=UserChatSettingsSchema)
async def update_chat_settings(
    settings_data: UserChatSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user's chat settings"""
    settings = db.query(UserChatSettings).filter(
        UserChatSettings.user_id == current_user.id
    ).first()
    
    if not settings:
        # Create new settings with provided data
        settings_dict = settings_data.dict(exclude_unset=True)
        settings = UserChatSettings(user_id=current_user.id, **settings_dict)
        db.add(settings)
    else:
        # Update existing settings
        update_data = settings_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(settings, field, value)
        settings.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(settings)
    
    return settings


# Admin Role Management
@router.get("/admin/users/{user_id}/roles", response_model=List[UserWithRole])
async def get_user_roles_admin(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all roles for a specific user (admin only)"""
    # Check if current user is admin
    if not await is_user_admin(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can view user roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    roles = await get_user_roles(db, user_id)
    return roles


@router.post("/admin/users/{user_id}/roles/admin")
async def assign_admin_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Assign admin role to a user (super admin only)"""
    # Only superusers can assign admin roles
    if not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only super administrators can assign admin roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = await assign_admin_role(db, user_id, current_user.id)
    return {"detail": f"Admin role assigned to {target_user.username}", "role": role}


@router.post("/admin/users/{user_id}/roles/moderator")
async def assign_moderator_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Assign moderator role to a user (admin only)"""
    # Check if current user is admin
    if not await is_user_admin(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can assign moderator roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = await assign_moderator_role(db, user_id, current_user.id)
    return {"detail": f"Moderator role assigned to {target_user.username}", "role": role}


@router.post("/admin/users/{user_id}/roles/vip")
async def assign_vip_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Assign VIP role to a user (admin only)"""
    # Check if current user is admin or moderator
    if not await is_user_staff(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only staff members can assign VIP roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = await assign_vip_role(db, user_id, current_user.id)
    return {"detail": f"VIP role assigned to {target_user.username}", "role": role}


@router.delete("/admin/users/{user_id}/roles/admin")
async def remove_admin_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove admin role from a user (super admin only)"""
    # Only superusers can remove admin roles
    if not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only super administrators can remove admin roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    success = await remove_admin_role(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User does not have admin role")
    
    return {"detail": f"Admin role removed from {target_user.username}"}


@router.delete("/admin/users/{user_id}/roles/moderator")
async def remove_moderator_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove moderator role from a user (admin only)"""
    # Check if current user is admin
    if not await is_user_admin(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can remove moderator roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    success = await remove_moderator_role(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User does not have moderator role")
    
    return {"detail": f"Moderator role removed from {target_user.username}"}


@router.delete("/admin/users/{user_id}/roles/vip")
async def remove_vip_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove VIP role from a user (admin only)"""
    # Check if current user is admin or moderator
    if not await is_user_staff(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only staff members can remove VIP roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    success = await remove_vip_role(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User does not have VIP role")
    
    return {"detail": f"VIP role removed from {target_user.username}"}


@router.post("/admin/users/{user_id}/roles/beta_tester")
async def assign_beta_tester_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Assign beta tester role to a user (admin only)"""
    # Check if current user is admin or staff
    if not await is_user_staff(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only staff members can assign beta tester roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = await assign_beta_tester_role(db, user_id, current_user.id)
    return {"detail": f"Beta tester role assigned to {target_user.username}", "role": role}


@router.delete("/admin/users/{user_id}/roles/beta_tester")
async def remove_beta_tester_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove beta tester role from a user (admin only)"""
    # Check if current user is admin or staff
    if not await is_user_staff(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only staff members can remove beta tester roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    success = await remove_beta_tester_role(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User does not have beta tester role")
    
    return {"detail": f"Beta tester role removed from {target_user.username}"}


@router.get("/admin/roles/admins")
async def list_all_admins(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all users with admin roles (admin only)"""
    # Check if current user is admin
    if not await is_user_admin(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can view admin list")
    
    admins = await get_all_admins(db)
    return {"admins": admins}


@router.get("/admin/roles/moderators")
async def list_all_moderators(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all users with moderator roles (admin only)"""
    # Check if current user is admin
    if not await is_user_admin(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can view moderator list")
    
    moderators = await get_all_moderators(db)
    return {"moderators": moderators}


@router.get("/admin/roles/beta_testers")
async def list_all_beta_testers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all users with beta tester roles (admin only)"""
    # Check if current user is admin or staff
    if not await is_user_staff(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only staff members can view beta tester list")
    
    beta_testers = await get_all_beta_testers(db)
    return {"beta_testers": beta_testers}


@router.post("/admin/users/{user_id}/sync-subscription-role")
async def sync_user_subscription_role_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sync user's chat role with their subscription tier (admin only)"""
    # Check if current user is admin
    if not await is_user_staff(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only staff members can sync user roles")
    
    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = await sync_user_subscription_role(db, user_id)
    return {"detail": f"Subscription role synced for {target_user.username}", "role": role}


# User Beta Status Endpoints
@router.get("/users/me/beta-status")
async def get_user_beta_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's beta testing status"""
    is_beta_tester = await is_user_beta_tester(db, current_user.id)
    is_admin = await is_user_admin(db, current_user.id)
    is_moderator = await is_user_moderator(db, current_user.id)
    
    # Admins and moderators have beta access
    has_beta_access = is_beta_tester or is_admin or is_moderator
    
    return {
        "is_beta_tester": is_beta_tester,
        "has_beta_access": has_beta_access,
        "is_admin": is_admin,
        "is_moderator": is_moderator
    }


@router.get("/users/me/beta-features")
async def get_user_beta_features_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of beta features available to current user"""
    from app.core.permissions import get_user_beta_features
    
    beta_features = await get_user_beta_features(db, current_user.id)
    is_beta_tester = await is_user_beta_tester(db, current_user.id)
    
    return {
        "features": beta_features,
        "is_beta_tester": is_beta_tester,
        "total_count": len(beta_features)
    }


# System Initialization
@router.post("/admin/initialize")
async def initialize_chat_system(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Initialize chat system with default channels (admin only)"""
    # Check if current user is admin or superuser
    if not await is_user_admin(db, current_user.id) and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can initialize the chat system")
    
    try:
        # Initialize default channels
        initialize_default_channels(db)
        
        # Get the created channels
        channels = db.query(ChatChannel).filter(ChatChannel.is_active == True).order_by(ChatChannel.sort_order).all()
        
        return {
            "detail": "Chat system initialized successfully",
            "channels_created": len(channels),
            "channels": [
                {
                    "id": channel.id,
                    "name": channel.name,
                    "description": channel.description,
                    "is_general": channel.is_general
                }
                for channel in channels
            ]
        }
        
    except Exception as e:
        print(f"Error initializing chat system: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize chat system: {str(e)}")


@router.post("/initialize-dev")
async def initialize_chat_system_dev(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Initialize chat system with default channels (development only - no admin check)"""
    try:
        # Initialize default channels
        initialize_default_channels(db)
        
        # Get the created channels
        channels = db.query(ChatChannel).filter(ChatChannel.is_active == True).order_by(ChatChannel.sort_order).all()
        
        return {
            "detail": "Chat system initialized successfully",
            "channels_created": len(channels),
            "channels": [
                {
                    "id": channel.id,
                    "name": channel.name,
                    "description": channel.description,
                    "is_general": channel.is_general
                }
                for channel in channels
            ]
        }
        
    except Exception as e:
        print(f"Error initializing chat system: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize chat system: {str(e)}")