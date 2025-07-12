# app/models/aria_context.py
from sqlalchemy import Boolean, Column, Integer, String, DateTime, Date, ForeignKey, Float, Text, JSON, Interval
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

class UserTradingProfile(Base):
    """
    Comprehensive user trading profile for ARIA context and pattern analysis
    """
    __tablename__ = "user_trading_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    
    # Basic Trading Metrics
    total_trades = Column(Integer, default=0)
    win_rate = Column(Float, nullable=True)  # Percentage (0.0-1.0)
    avg_hold_time = Column(Integer, nullable=True)  # Minutes
    avg_profit_per_trade = Column(Float, nullable=True)
    avg_loss_per_trade = Column(Float, nullable=True)
    
    # Trading Preferences
    preferred_timeframes = Column(JSON, nullable=True)  # ["1m", "5m", "1h"]
    preferred_instruments = Column(JSON, nullable=True)  # ["AAPL", "ES", "EUR/USD"]
    risk_tolerance = Column(String, default="moderate")  # "conservative", "moderate", "aggressive"
    max_position_size = Column(Float, nullable=True)
    preferred_brokers = Column(JSON, nullable=True)  # ["tradovate", "interactive_brokers"]
    
    # Pattern Analysis Data (Future-ready)
    best_trading_hours = Column(JSON, nullable=True)  # [9, 10, 11] (hours when profitable)
    worst_trading_days = Column(JSON, nullable=True)  # [2, 4] (Tuesday=2, Thursday=4)
    monthly_performance = Column(JSON, nullable=True)  # {"2024-01": {"pnl": 1500, "trades": 45}}
    seasonal_patterns = Column(JSON, nullable=True)  # Market condition preferences
    
    # Behavioral Insights (Future-ready)
    revenge_trading_tendency = Column(Float, default=0.0)  # 0.0-1.0 score
    overtrading_tendency = Column(Float, default=0.0)  # 0.0-1.0 score
    risk_management_score = Column(Float, default=0.5)  # 0.0-1.0 score
    emotional_trading_score = Column(Float, default=0.5)  # 0.0-1.0 score
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_analysis_update = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="trading_profile")
    trading_sessions = relationship("UserTradingSession", back_populates="user_profile", cascade="all, delete-orphan")
    aria_interactions = relationship("ARIAInteraction", back_populates="user_profile")

class UserTradingSession(Base):
    """
    Individual trading session tracking for behavioral analysis
    """
    __tablename__ = "user_trading_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_profile_id = Column(Integer, ForeignKey("user_trading_profiles.id"), index=True)
    
    # Session Info
    session_date = Column(Date, index=True)
    start_time = Column(DateTime)
    end_time = Column(DateTime, nullable=True)
    session_duration = Column(Integer, nullable=True)  # Minutes
    
    # Session Performance
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    session_pnl = Column(Float, default=0.0)
    largest_winner = Column(Float, default=0.0)
    largest_loser = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    
    # Session Context
    market_conditions = Column(JSON, nullable=True)  # VIX, market direction, volatility
    active_strategies = Column(JSON, nullable=True)  # Strategies used during session
    brokers_used = Column(JSON, nullable=True)  # Which brokers were active
    
    # Behavioral Analysis (Future-ready)
    emotions_detected = Column(JSON, nullable=True)  # ["fear", "greed", "confidence"]
    trading_mistakes = Column(JSON, nullable=True)  # Pattern violations, revenge trades
    session_notes = Column(Text, nullable=True)  # User or AI-generated notes
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user_profile = relationship("UserTradingProfile", back_populates="trading_sessions")
    aria_interactions = relationship("ARIAInteraction", back_populates="trading_session")

class ARIAInteraction(Base):
    """
    Complete log of all ARIA interactions for learning and context
    """
    __tablename__ = "aria_interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_profile_id = Column(Integer, ForeignKey("user_trading_profiles.id"), index=True)
    trading_session_id = Column(Integer, ForeignKey("user_trading_sessions.id"), nullable=True, index=True)
    
    # Interaction Details
    interaction_type = Column(String, index=True)  # "voice", "text", "action", "proactive"
    input_method = Column(String)  # "voice", "text", "button"
    raw_input = Column(Text)  # Original user input
    processed_command = Column(Text, nullable=True)  # Cleaned/processed version
    
    # Intent Recognition
    detected_intent = Column(String, nullable=True)  # "strategy_control", "position_query", etc.
    intent_confidence = Column(Float, nullable=True)  # 0.0-1.0
    intent_parameters = Column(JSON, nullable=True)  # Extracted parameters
    
    # AI Processing
    ai_model_used = Column(String, nullable=True)  # "claude", "deepseek"
    processing_time_ms = Column(Integer, nullable=True)
    context_used = Column(JSON, nullable=True)  # What context was provided to AI
    
    # Response Generation
    aria_response = Column(Text, nullable=True)
    response_type = Column(String, nullable=True)  # "text", "voice", "action", "error"
    response_time_ms = Column(Integer, nullable=True)
    
    # Action Execution
    action_attempted = Column(String, nullable=True)  # "strategy_enable", "position_close", etc.
    action_parameters = Column(JSON, nullable=True)  # Action details
    action_success = Column(Boolean, nullable=True)
    action_result = Column(JSON, nullable=True)  # Execution results
    
    # User Feedback
    user_satisfaction = Column(Integer, nullable=True)  # 1-5 rating
    user_feedback = Column(Text, nullable=True)
    followup_needed = Column(Boolean, default=False)
    
    # Security & Compliance
    required_confirmation = Column(Boolean, default=False)
    confirmation_provided = Column(Boolean, nullable=True)
    risk_level = Column(String, default="low")  # "low", "medium", "high"
    
    # Timestamps
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    response_timestamp = Column(DateTime, nullable=True)
    action_timestamp = Column(DateTime, nullable=True)
    
    # Relationships
    user_profile = relationship("UserTradingProfile", back_populates="aria_interactions")
    trading_session = relationship("UserTradingSession", back_populates="aria_interactions")

class ARIAContextCache(Base):
    """
    Cache frequently accessed user context for performance
    """
    __tablename__ = "aria_context_cache"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    
    # Cache Data
    cache_key = Column(String, index=True)  # "positions", "strategies", "performance"
    cache_data = Column(JSON)  # Cached context data
    cache_timestamp = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, index=True)
    
    # Cache Metadata
    data_source = Column(String)  # "broker_api", "database", "calculation"
    cache_hit_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User")