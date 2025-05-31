# app/models/chat.py
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base


class ChatChannel(Base):
    __tablename__ = "chat_channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    is_general = Column(Boolean, default=False, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    sort_order = Column(Integer, default=0, nullable=False)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    messages = relationship("ChatMessage", back_populates="channel", cascade="all, delete-orphan")
    members = relationship("ChatChannelMember", back_populates="channel", cascade="all, delete-orphan")

    def __str__(self):
        return f"ChatChannel(name={self.name})"


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    original_content = Column(Text, nullable=True)  # For edit history
    is_edited = Column(Boolean, default=False, nullable=False)
    edited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    reply_to_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    channel = relationship("ChatChannel", back_populates="messages")
    user = relationship("User", foreign_keys=[user_id])
    reply_to = relationship("ChatMessage", remote_side=[id])
    reactions = relationship("ChatReaction", back_populates="message", cascade="all, delete-orphan")

    def __str__(self):
        return f"ChatMessage(id={self.id}, channel={self.channel_id})"


class ChatReaction(Base):
    __tablename__ = "chat_reactions"
    __table_args__ = (
        UniqueConstraint('message_id', 'user_id', 'emoji', name='unique_reaction_per_user'),
    )

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    emoji = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    message = relationship("ChatMessage", back_populates="reactions")
    user = relationship("User")

    def __str__(self):
        return f"ChatReaction(message={self.message_id}, user={self.user_id}, emoji={self.emoji})"


class UserChatRole(Base):
    __tablename__ = "user_chat_roles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_name = Column(String(50), nullable=False)
    role_color = Column(String(7), nullable=False)  # Hex color code
    role_priority = Column(Integer, default=0, nullable=False, index=True)  # Higher = more important
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    assigned_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    assigned_by_user = relationship("User", foreign_keys=[assigned_by])

    def __str__(self):
        return f"UserChatRole(user={self.user_id}, role={self.role_name})"


class UserChatSettings(Base):
    __tablename__ = "user_chat_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    show_profile_pictures = Column(Boolean, default=True, nullable=False)
    notification_sound = Column(Boolean, default=True, nullable=False)
    compact_mode = Column(Boolean, default=False, nullable=False)
    theme = Column(String(20), default='dark', nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User")

    def __str__(self):
        return f"UserChatSettings(user={self.user_id})"


class ChatChannelMember(Base):
    __tablename__ = "chat_channel_members"
    __table_args__ = (
        UniqueConstraint('channel_id', 'user_id', name='unique_channel_member'),
    )

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_read_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    is_muted = Column(Boolean, default=False, nullable=False)

    # Relationships
    channel = relationship("ChatChannel", back_populates="members")
    user = relationship("User")

    def __str__(self):
        return f"ChatChannelMember(channel={self.channel_id}, user={self.user_id})"