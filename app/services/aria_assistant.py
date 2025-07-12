# app/services/aria_assistant.py
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
import logging
import asyncio
from enum import Enum

from ..models.aria_context import (
    UserTradingProfile, 
    UserTradingSession, 
    ARIAInteraction, 
    ARIAContextCache
)
from ..models.user import User
from ..models.strategy import ActivatedStrategy
from ..models.broker import BrokerAccount
from .intent_service import IntentService, VoiceIntent
from .aria_context_engine import ARIAContextEngine
from .aria_action_executor import ARIAActionExecutor

logger = logging.getLogger(__name__)

class ARIAResponseType(Enum):
    TEXT = "text"
    VOICE = "voice"
    ACTION = "action"
    ERROR = "error"
    CONFIRMATION = "confirmation"

class ARIARiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ARIAAssistant:
    """
    Main ARIA Assistant service - orchestrates all ARIA functionality
    
    This is the central coordinator that:
    1. Processes user input (voice/text)
    2. Understands intent and context
    3. Executes actions safely
    4. Generates intelligent responses
    5. Learns from interactions
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.intent_service = IntentService()
        self.context_engine = ARIAContextEngine(db)
        self.action_executor = ARIAActionExecutor(db)
        
    async def process_user_input(
        self, 
        user_id: int, 
        input_text: str, 
        input_type: str = "text"
    ) -> Dict[str, Any]:
        """
        Main entry point for all ARIA interactions
        
        Args:
            user_id: User's database ID
            input_text: Raw user input (voice transcript or typed text)
            input_type: "voice" or "text"
            
        Returns:
            Complete response with action results and ARIA reply
        """
        interaction_start = datetime.utcnow()
        
        try:
            # 1. Get or create user trading profile
            user_profile = await self._get_or_create_user_profile(user_id)
            
            # 2. Get comprehensive user context
            user_context = await self.context_engine.get_user_context(user_id)
            
            # 3. Process intent from user input
            intent = await self.intent_service.parse_voice_command(input_text)
            
            # 4. Determine risk level and confirmation requirements
            risk_level = self._assess_risk_level(intent, user_context)
            requires_confirmation = self._requires_confirmation(intent, risk_level)
            
            # 5. Create interaction record
            interaction = await self._create_interaction_record(
                user_profile.id,
                input_text,
                input_type,
                intent,
                risk_level,
                requires_confirmation
            )
            
            # 6. Handle confirmation flow if needed
            if requires_confirmation and not intent.confirmed:
                return await self._handle_confirmation_request(interaction, intent, user_context)
            
            # 7. Execute action if required
            action_result = None
            if intent.requires_action:
                action_result = await self.action_executor.execute_action(
                    user_id, intent, user_context
                )
                
                # Update interaction with action results
                await self._update_interaction_action_result(
                    interaction, action_result
                )
            
            # 8. Generate ARIA response
            response = await self._generate_aria_response(
                user_context, intent, action_result, input_type
            )
            
            # 9. Update interaction with response
            await self._update_interaction_response(interaction, response)
            
            # 10. Update user context cache
            await self.context_engine.update_context_cache(user_id)
            
            return {
                "success": True,
                "interaction_id": interaction.id,
                "response": response,
                "action_result": action_result,
                "requires_confirmation": False,
                "risk_level": risk_level.value,
                "processing_time_ms": int((datetime.utcnow() - interaction_start).total_seconds() * 1000)
            }
            
        except Exception as e:
            logger.error(f"ARIA processing error for user {user_id}: {str(e)}")
            
            # Create error interaction record
            error_interaction = await self._create_error_interaction(
                user_id, input_text, input_type, str(e)
            )
            
            return {
                "success": False,
                "interaction_id": error_interaction.id,
                "error": str(e),
                "response": {
                    "text": "I'm sorry, I encountered an error processing your request. Please try again.",
                    "type": ARIAResponseType.ERROR.value
                },
                "processing_time_ms": int((datetime.utcnow() - interaction_start).total_seconds() * 1000)
            }
    
    async def execute_voice_command(
        self, 
        user_id: int, 
        command: str
    ) -> Dict[str, Any]:
        """
        Specialized method for voice commands with optimized processing
        """
        return await self.process_user_input(user_id, command, "voice")
    
    async def handle_confirmation_response(
        self, 
        user_id: int, 
        interaction_id: int, 
        confirmed: bool
    ) -> Dict[str, Any]:
        """
        Handle user's response to a confirmation request
        """
        try:
            # Get original interaction
            interaction = self.db.query(ARIAInteraction).filter(
                ARIAInteraction.id == interaction_id
            ).first()
            
            if not interaction:
                raise ValueError(f"Interaction {interaction_id} not found")
            
            # Update confirmation status
            interaction.confirmation_provided = confirmed
            
            if confirmed:
                # Execute the original action
                intent = VoiceIntent(
                    type=interaction.detected_intent,
                    parameters=interaction.intent_parameters,
                    confidence=interaction.intent_confidence,
                    confirmed=True
                )
                
                user_context = await self.context_engine.get_user_context(user_id)
                action_result = await self.action_executor.execute_action(
                    user_id, intent, user_context
                )
                
                # Update interaction with results
                await self._update_interaction_action_result(interaction, action_result)
                
                response = await self._generate_aria_response(
                    user_context, intent, action_result, "text"
                )
                
                await self._update_interaction_response(interaction, response)
                
                return {
                    "success": True,
                    "confirmed": True,
                    "action_result": action_result,
                    "response": response
                }
            else:
                # User declined - generate cancellation response
                response = {
                    "text": "Action cancelled. Is there anything else I can help you with?",
                    "type": ARIAResponseType.TEXT.value
                }
                
                await self._update_interaction_response(interaction, response)
                
                return {
                    "success": True,
                    "confirmed": False,
                    "response": response
                }
                
        except Exception as e:
            logger.error(f"Confirmation handling error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": {
                    "text": "I encountered an error processing your confirmation. Please try again.",
                    "type": ARIAResponseType.ERROR.value
                }
            }
    
    async def get_user_context_summary(self, user_id: int) -> Dict[str, Any]:
        """
        Get a comprehensive summary of user's trading context for ARIA
        """
        return await self.context_engine.get_user_context(user_id)
    
    async def _get_or_create_user_profile(self, user_id: int) -> UserTradingProfile:
        """Get existing user profile or create a new one"""
        profile = self.db.query(UserTradingProfile).filter(
            UserTradingProfile.user_id == user_id
        ).first()
        
        if not profile:
            profile = UserTradingProfile(
                user_id=user_id,
                risk_tolerance="moderate",
                created_at=datetime.utcnow()
            )
            self.db.add(profile)
            self.db.commit()
            self.db.refresh(profile)
            
        return profile
    
    def _assess_risk_level(
        self, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> ARIARiskLevel:
        """
        Assess the risk level of the requested action
        """
        if intent.type == "position_query" or intent.type == "strategy_status":
            return ARIARiskLevel.LOW
        
        if intent.type == "strategy_control":
            return ARIARiskLevel.MEDIUM
        
        if intent.type == "trade_execution":
            # Check position size
            if intent.parameters.get("quantity", 0) > 1000:  # Large position
                return ARIARiskLevel.HIGH
            return ARIARiskLevel.MEDIUM
        
        if intent.type == "account_control":
            return ARIARiskLevel.CRITICAL
        
        return ARIARiskLevel.LOW
    
    def _requires_confirmation(
        self, 
        intent: VoiceIntent, 
        risk_level: ARIARiskLevel
    ) -> bool:
        """
        Determine if action requires user confirmation
        """
        # Always require confirmation for medium risk and above
        if risk_level in [ARIARiskLevel.MEDIUM, ARIARiskLevel.HIGH, ARIARiskLevel.CRITICAL]:
            return True
        
        # No confirmation needed for queries
        if intent.type in ["position_query", "strategy_status", "performance_query"]:
            return False
        
        return False
    
    async def _create_interaction_record(
        self,
        user_profile_id: int,
        raw_input: str,
        input_type: str,
        intent: VoiceIntent,
        risk_level: ARIARiskLevel,
        requires_confirmation: bool
    ) -> ARIAInteraction:
        """Create a new interaction record"""
        interaction = ARIAInteraction(
            user_profile_id=user_profile_id,
            interaction_type=input_type,
            input_method=input_type,
            raw_input=raw_input,
            detected_intent=intent.type,
            intent_confidence=intent.confidence,
            intent_parameters=intent.parameters,
            required_confirmation=requires_confirmation,
            risk_level=risk_level.value,
            timestamp=datetime.utcnow()
        )
        
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        
        return interaction
    
    async def _create_error_interaction(
        self,
        user_id: int,
        raw_input: str,
        input_type: str,
        error_message: str
    ) -> ARIAInteraction:
        """Create error interaction record"""
        user_profile = await self._get_or_create_user_profile(user_id)
        
        interaction = ARIAInteraction(
            user_profile_id=user_profile.id,
            interaction_type=input_type,
            input_method=input_type,
            raw_input=raw_input,
            aria_response=f"Error: {error_message}",
            response_type=ARIAResponseType.ERROR.value,
            action_success=False,
            timestamp=datetime.utcnow()
        )
        
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        
        return interaction
    
    async def _handle_confirmation_request(
        self,
        interaction: ARIAInteraction,
        intent: VoiceIntent,
        user_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate confirmation request for risky actions"""
        confirmation_text = self._generate_confirmation_text(intent, user_context)
        
        response = {
            "text": confirmation_text,
            "type": ARIAResponseType.CONFIRMATION.value,
            "requires_confirmation": True,
            "interaction_id": interaction.id,
            "intent_summary": self._generate_intent_summary(intent)
        }
        
        await self._update_interaction_response(interaction, response)
        
        return {
            "success": True,
            "requires_confirmation": True,
            "response": response,
            "interaction_id": interaction.id
        }
    
    def _generate_confirmation_text(
        self, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> str:
        """Generate appropriate confirmation text based on intent"""
        if intent.type == "strategy_control":
            strategy_name = intent.parameters.get("strategy_name", "strategy")
            action = intent.parameters.get("action", "activate")
            
            return f"I'll {action} your {strategy_name} strategy. This will affect your automated trading. Confirm: Yes or No?"
        
        elif intent.type == "trade_execution":
            action = intent.parameters.get("action", "buy")
            quantity = intent.parameters.get("quantity", "")
            symbol = intent.parameters.get("symbol", "")
            
            return f"I'll {action} {quantity} shares of {symbol}. Confirm this trade: Yes or No?"
        
        elif intent.type == "account_control":
            action = intent.parameters.get("action", "")
            return f"I'll {action} for your account. This is a high-risk action. Confirm: Yes or No?"
        
        return "Confirm this action: Yes or No?"
    
    def _generate_intent_summary(self, intent: VoiceIntent) -> Dict[str, Any]:
        """Generate human-readable intent summary"""
        return {
            "action": intent.type,
            "parameters": intent.parameters,
            "confidence": intent.confidence,
            "description": self._intent_to_description(intent)
        }
    
    def _intent_to_description(self, intent: VoiceIntent) -> str:
        """Convert intent to human-readable description"""
        if intent.type == "strategy_control":
            strategy = intent.parameters.get("strategy_name", "strategy")
            action = intent.parameters.get("action", "control")
            return f"{action.title()} {strategy} strategy"
        
        elif intent.type == "trade_execution":
            action = intent.parameters.get("action", "trade")
            symbol = intent.parameters.get("symbol", "")
            quantity = intent.parameters.get("quantity", "")
            return f"{action.title()} {quantity} {symbol}"
        
        return intent.type.replace("_", " ").title()
    
    async def _update_interaction_action_result(
        self,
        interaction: ARIAInteraction,
        action_result: Dict[str, Any]
    ):
        """Update interaction with action execution results"""
        interaction.action_attempted = action_result.get("action_type")
        interaction.action_parameters = action_result.get("parameters")
        interaction.action_success = action_result.get("success", False)
        interaction.action_result = action_result
        interaction.action_timestamp = datetime.utcnow()
        
        self.db.commit()
    
    async def _update_interaction_response(
        self,
        interaction: ARIAInteraction,
        response: Dict[str, Any]
    ):
        """Update interaction with ARIA response"""
        interaction.aria_response = response.get("text", "")
        interaction.response_type = response.get("type", ARIAResponseType.TEXT.value)
        interaction.response_timestamp = datetime.utcnow()
        
        self.db.commit()
    
    async def _generate_aria_response(
        self,
        user_context: Dict[str, Any],
        intent: VoiceIntent,
        action_result: Optional[Dict[str, Any]],
        input_type: str
    ) -> Dict[str, Any]:
        """
        Generate intelligent ARIA response based on context and results
        """
        
        # If action was executed, generate result-based response
        if action_result:
            if action_result.get("success"):
                return self._generate_success_response(intent, action_result, input_type)
            else:
                return self._generate_error_response(intent, action_result, input_type)
        
        # Query responses
        if intent.type == "position_query":
            return self._generate_position_response(user_context, intent, input_type)
        
        elif intent.type == "strategy_status":
            return self._generate_strategy_status_response(user_context, intent, input_type)
        
        elif intent.type == "performance_query":
            return self._generate_performance_response(user_context, intent, input_type)
        
        # Default response
        return {
            "text": "I understand your request. How else can I help you with your trading?",
            "type": ARIAResponseType.TEXT.value
        }
    
    def _generate_success_response(
        self, 
        intent: VoiceIntent, 
        action_result: Dict[str, Any], 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for successful actions"""
        if intent.type == "strategy_control":
            strategy_name = intent.parameters.get("strategy_name", "strategy")
            action = intent.parameters.get("action", "updated")
            text = f"✅ {strategy_name} strategy has been {action}. I'll monitor its performance for you."
        
        elif intent.type == "trade_execution":
            symbol = intent.parameters.get("symbol", "")
            action = intent.parameters.get("action", "executed")
            text = f"✅ Trade {action} for {symbol}. Order details: {action_result.get('order_id', 'Processing')}"
        
        else:
            text = f"✅ Action completed successfully."
        
        return {
            "text": text,
            "type": ARIAResponseType.TEXT.value,
            "action_result": action_result
        }
    
    def _generate_error_response(
        self, 
        intent: VoiceIntent, 
        action_result: Dict[str, Any], 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for failed actions"""
        error_message = action_result.get("error", "Unknown error occurred")
        
        text = f"❌ I couldn't complete that action. {error_message}. Would you like me to try again or help you with something else?"
        
        return {
            "text": text,
            "type": ARIAResponseType.ERROR.value,
            "error_details": action_result
        }
    
    def _generate_position_response(
        self, 
        user_context: Dict[str, Any], 
        intent: VoiceIntent, 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for position queries"""
        symbol = intent.parameters.get("symbol", "").upper()
        positions = user_context.get("current_positions", {})
        
        if symbol in positions:
            position = positions[symbol]
            text = f"📊 Your {symbol} position: {position.get('quantity', 0)} shares, P&L: ${position.get('unrealized_pnl', 0):.2f}"
        else:
            text = f"📊 You don't currently have a {symbol} position."
        
        return {
            "text": text,
            "type": ARIAResponseType.TEXT.value,
            "position_data": positions.get(symbol)
        }
    
    def _generate_strategy_status_response(
        self, 
        user_context: Dict[str, Any], 
        intent: VoiceIntent, 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for strategy status queries"""
        strategies = user_context.get("active_strategies", [])
        
        if strategies:
            active_count = len([s for s in strategies if s.get("is_active")])
            text = f"🤖 You have {active_count} active strategies running: {', '.join([s.get('name', 'Unknown') for s in strategies[:3]])}"
            if len(strategies) > 3:
                text += f" and {len(strategies) - 3} more."
        else:
            text = "🤖 No strategies are currently active. Would you like me to help you activate one?"
        
        return {
            "text": text,
            "type": ARIAResponseType.TEXT.value,
            "strategy_data": strategies
        }
    
    def _generate_performance_response(
        self, 
        user_context: Dict[str, Any], 
        intent: VoiceIntent, 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for performance queries"""
        performance = user_context.get("performance_summary", {})
        
        daily_pnl = performance.get("daily_pnl", 0)
        total_trades = performance.get("total_trades_today", 0)
        
        if daily_pnl > 0:
            emoji = "📈"
            status = "up"
        elif daily_pnl < 0:
            emoji = "📉"
            status = "down"
        else:
            emoji = "➡️"
            status = "flat"
        
        text = f"{emoji} Today you're {status} ${abs(daily_pnl):.2f} with {total_trades} trades."
        
        return {
            "text": text,
            "type": ARIAResponseType.TEXT.value,
            "performance_data": performance
        }