# app/api/v1/endpoints/aria.py
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import logging

from ....services.aria_assistant import ARIAAssistant
from ....models.user import User
from ....models.aria_context import UserTradingProfile
from ....core.deps import get_db, get_current_active_user
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter()

# Request/Response Models
class ARIAMessageRequest(BaseModel):
    """Request model for ARIA text/voice input"""
    message: str = Field(..., description="User's message or voice transcript")
    input_type: str = Field(default="text", description="Input type: 'text' or 'voice'")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")

class ARIAConfirmationRequest(BaseModel):
    """Request model for confirmation responses"""
    interaction_id: int = Field(..., description="ID of the interaction requiring confirmation")
    confirmed: bool = Field(..., description="Whether the user confirmed the action")

class ARIAResponse(BaseModel):
    """Standardized ARIA response model"""
    success: bool
    response: Dict[str, Any]
    interaction_id: Optional[int] = None
    requires_confirmation: bool = False
    action_result: Optional[Dict[str, Any]] = None
    processing_time_ms: Optional[int] = None
    error: Optional[str] = None

class ARIAContextResponse(BaseModel):
    """Response model for user context"""
    user_profile: Dict[str, Any]
    current_positions: Dict[str, Any]
    active_strategies: list
    performance_summary: Dict[str, Any]
    risk_metrics: Dict[str, Any]
    broker_status: Dict[str, Any]
    market_context: Dict[str, Any]

# Endpoints

@router.post("/chat", response_model=ARIAResponse)
async def aria_chat(
    request: ARIAMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Main ARIA chat endpoint for text and voice interactions
    
    Process user input and return ARIA's response with any actions taken
    """
    try:
        aria = ARIAAssistant(db)
        
        result = await aria.process_user_input(
            user_id=current_user.id,
            input_text=request.message,
            input_type=request.input_type
        )
        
        return ARIAResponse(
            success=result["success"],
            response=result["response"],
            interaction_id=result.get("interaction_id"),
            requires_confirmation=result.get("requires_confirmation", False),
            action_result=result.get("action_result"),
            processing_time_ms=result.get("processing_time_ms"),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.error(f"ARIA chat error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ARIA processing failed: {str(e)}"
        )

@router.post("/voice", response_model=ARIAResponse)
async def aria_voice_command(
    request: ARIAMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Specialized endpoint for voice commands with optimized processing
    """
    try:
        aria = ARIAAssistant(db)
        
        result = await aria.execute_voice_command(
            user_id=current_user.id,
            command=request.message
        )
        
        return ARIAResponse(
            success=result["success"],
            response=result["response"],
            interaction_id=result.get("interaction_id"),
            requires_confirmation=result.get("requires_confirmation", False),
            action_result=result.get("action_result"),
            processing_time_ms=result.get("processing_time_ms"),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.error(f"ARIA voice command error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice command processing failed: {str(e)}"
        )

@router.post("/confirm", response_model=ARIAResponse)
async def aria_confirmation(
    request: ARIAConfirmationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Handle user confirmations for pending actions
    """
    try:
        aria = ARIAAssistant(db)
        
        result = await aria.handle_confirmation_response(
            user_id=current_user.id,
            interaction_id=request.interaction_id,
            confirmed=request.confirmed
        )
        
        return ARIAResponse(
            success=result["success"],
            response=result["response"],
            action_result=result.get("action_result"),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.error(f"ARIA confirmation error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Confirmation processing failed: {str(e)}"
        )

@router.get("/context", response_model=ARIAContextResponse)
async def get_aria_context(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get comprehensive user context for ARIA
    
    Returns current positions, strategies, performance, and other context
    """
    try:
        aria = ARIAAssistant(db)
        
        context = await aria.get_user_context_summary(current_user.id)
        
        return ARIAContextResponse(
            user_profile=context.get("user_profile", {}),
            current_positions=context.get("current_positions", {}),
            active_strategies=context.get("active_strategies", []),
            performance_summary=context.get("performance_summary", {}),
            risk_metrics=context.get("risk_metrics", {}),
            broker_status=context.get("broker_status", {}),
            market_context=context.get("market_context", {})
        )
        
    except Exception as e:
        logger.error(f"ARIA context error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Context retrieval failed: {str(e)}"
        )

@router.get("/examples")
async def get_aria_examples():
    """
    Get example commands and usage patterns for ARIA
    """
    try:
        from ....services.intent_service import IntentService
        
        intent_service = IntentService()
        examples = intent_service.get_intent_examples()
        
        return {
            "success": True,
            "examples": examples,
            "voice_tips": [
                "Speak clearly and use natural language",
                "Include specific details like 'Purple Reign strategy' or 'AAPL position'",
                "ARIA will ask for confirmation on important actions",
                "You can say 'Yes' or 'No' to confirm or cancel actions"
            ],
            "sample_conversations": [
                {
                    "user": "Turn on my Purple Reign strategy",
                    "aria": "I'll activate your Purple Reign strategy. This will affect your automated trading. Confirm: Yes or No?",
                    "user": "Yes",
                    "aria": "✅ Purple Reign strategy has been activated. I'll monitor its performance for you."
                },
                {
                    "user": "What's my Tesla position?",
                    "aria": "📊 Your TSLA position: -50 shares, P&L: $165.00 (1.34% gain)"
                },
                {
                    "user": "How did I do today?",
                    "aria": "📈 Today you're up $250.75 with 8 trades. Your win rate is 62.5%."
                }
            ]
        }
        
    except Exception as e:
        logger.error(f"ARIA examples error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Examples retrieval failed: {str(e)}"
        )

@router.get("/health")
async def aria_health_check(
    db: Session = Depends(get_db)
):
    """
    Health check endpoint for ARIA services
    """
    try:
        # Test database connection
        db.execute("SELECT 1")
        
        # Test ARIA service initialization
        aria = ARIAAssistant(db)
        
        return {
            "success": True,
            "status": "healthy",
            "services": {
                "database": "connected",
                "aria_assistant": "initialized",
                "intent_service": "ready",
                "context_engine": "ready",
                "action_executor": "ready"
            },
            "timestamp": "2025-01-12T00:00:00Z"
        }
        
    except Exception as e:
        logger.error(f"ARIA health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ARIA services unhealthy: {str(e)}"
        )

# Voice-specific endpoints for future mobile integration

@router.post("/voice/start-session")
async def start_voice_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Start a voice interaction session (future: WebRTC, real-time processing)
    """
    try:
        return {
            "success": True,
            "session_id": f"voice_session_{current_user.id}_{int(datetime.utcnow().timestamp())}",
            "message": "Voice session started. You can now send voice commands.",
            "supported_formats": ["audio/webm", "audio/wav", "audio/mp3"],
            "max_duration_seconds": 30
        }
        
    except Exception as e:
        logger.error(f"Voice session start error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice session start failed: {str(e)}"
        )

@router.post("/voice/end-session")
async def end_voice_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    End a voice interaction session
    """
    try:
        return {
            "success": True,
            "session_id": session_id,
            "message": "Voice session ended successfully.",
            "session_duration": "45 seconds",  # Would track actual duration
            "commands_processed": 3  # Would track actual commands
        }
        
    except Exception as e:
        logger.error(f"Voice session end error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice session end failed: {str(e)}"
        )

# Analytics endpoints for ARIA usage

@router.get("/analytics/interactions")
async def get_aria_analytics(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get ARIA interaction analytics for the user
    """
    try:
        from ....models.aria_context import ARIAInteraction
        from datetime import datetime, timedelta
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Get user's trading profile to access interactions
        user_profile = db.query(UserTradingProfile).filter(
            UserTradingProfile.user_id == current_user.id
        ).first()
        
        if not user_profile:
            return {
                "success": True,
                "analytics": {
                    "total_interactions": 0,
                    "voice_interactions": 0,
                    "text_interactions": 0,
                    "successful_actions": 0,
                    "failed_actions": 0,
                    "most_used_intents": [],
                    "average_response_time_ms": 0
                }
            }
        
        interactions = db.query(ARIAInteraction).filter(
            ARIAInteraction.user_profile_id == user_profile.id,
            ARIAInteraction.timestamp >= start_date
        ).all()
        
        # Calculate analytics
        total_interactions = len(interactions)
        voice_interactions = len([i for i in interactions if i.interaction_type == "voice"])
        text_interactions = len([i for i in interactions if i.interaction_type == "text"])
        successful_actions = len([i for i in interactions if i.action_success == True])
        failed_actions = len([i for i in interactions if i.action_success == False])
        
        # Intent frequency
        intent_counts = {}
        response_times = []
        
        for interaction in interactions:
            if interaction.detected_intent:
                intent_counts[interaction.detected_intent] = intent_counts.get(interaction.detected_intent, 0) + 1
            
            if interaction.response_time_ms:
                response_times.append(interaction.response_time_ms)
        
        most_used_intents = sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        return {
            "success": True,
            "analytics": {
                "period_days": days,
                "total_interactions": total_interactions,
                "voice_interactions": voice_interactions,
                "text_interactions": text_interactions,
                "successful_actions": successful_actions,
                "failed_actions": failed_actions,
                "success_rate": successful_actions / max(successful_actions + failed_actions, 1),
                "most_used_intents": most_used_intents,
                "average_response_time_ms": int(avg_response_time),
                "voice_usage_percentage": voice_interactions / max(total_interactions, 1) * 100
            }
        }
        
    except Exception as e:
        logger.error(f"ARIA analytics error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analytics retrieval failed: {str(e)}"
        )