# app/schemas/chat.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# Chat Channel Schemas
class ChatChannelBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    is_general: bool = False


class ChatChannelCreate(ChatChannelBase):
    pass


class ChatChannelUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class ChatChannel(ChatChannelBase):
    id: int
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    is_active: bool
    sort_order: int
    
    class Config:
        from_attributes = True


# Chat Message Schemas
class ChatMessageBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    reply_to_id: Optional[int] = None


class ChatMessageCreate(ChatMessageBase):
    pass


class ChatMessageUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class ChatReactionSummary(BaseModel):
    emoji: str
    count: int
    users: List[str]  # List of usernames who reacted


class ChatMessage(ChatMessageBase):
    id: int
    channel_id: int
    user_id: int
    user_name: str
    user_role_color: str
    is_edited: bool
    edited_at: Optional[datetime]
    created_at: datetime
    is_deleted: bool
    reactions: List[ChatReactionSummary] = []
    
    class Config:
        from_attributes = True


# Chat Reaction Schemas
class ChatReactionCreate(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=10)


class ChatReaction(BaseModel):
    id: int
    message_id: int
    user_id: int
    emoji: str
    created_at: datetime
    
    class Config:
        from_attributes = True


# User Chat Role Schemas
class UserChatRoleBase(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=50)
    role_color: str = Field(..., pattern=r'^#[0-9A-Fa-f]{6}$')  # Hex color validation
    role_priority: int = Field(default=0, ge=0, le=100)


class UserChatRoleCreate(UserChatRoleBase):
    user_id: int


class UserChatRoleUpdate(BaseModel):
    role_name: Optional[str] = Field(None, min_length=1, max_length=50)
    role_color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')
    role_priority: Optional[int] = Field(None, ge=0, le=100)
    is_active: Optional[bool] = None


class UserChatRole(UserChatRoleBase):
    id: int
    user_id: int
    assigned_at: datetime
    assigned_by: Optional[int]
    is_active: bool
    
    class Config:
        from_attributes = True


# User Chat Settings Schemas
class UserChatSettingsBase(BaseModel):
    show_profile_pictures: bool = True
    notification_sound: bool = True
    compact_mode: bool = False
    theme: str = Field(default='dark', pattern=r'^(dark|light)$')


class UserChatSettingsUpdate(BaseModel):
    show_profile_pictures: Optional[bool] = None
    notification_sound: Optional[bool] = None
    compact_mode: Optional[bool] = None
    theme: Optional[str] = Field(None, pattern=r'^(dark|light)$')


class UserChatSettings(UserChatSettingsBase):
    user_id: int
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Chat Channel Member Schemas
class ChatChannelMemberBase(BaseModel):
    is_muted: bool = False


class ChatChannelMemberCreate(ChatChannelMemberBase):
    channel_id: int
    user_id: int


class ChatChannelMemberUpdate(BaseModel):
    is_muted: Optional[bool] = None
    last_read_at: Optional[datetime] = None


class ChatChannelMember(ChatChannelMemberBase):
    id: int
    channel_id: int
    user_id: int
    joined_at: datetime
    last_read_at: datetime
    
    class Config:
        from_attributes = True


# Response Schemas
class ChatChannelWithUnreadCount(ChatChannel):
    unread_count: int = 0


class ChatMessageList(BaseModel):
    messages: List[ChatMessage]
    total_count: int
    has_more: bool


class ChatEventData(BaseModel):
    type: str
    data: dict


# Role management response
class UserWithRole(BaseModel):
    id: int
    username: str
    role_name: Optional[str] = None
    role_color: Optional[str] = None
    role_priority: Optional[int] = None
    
    class Config:
        from_attributes = True