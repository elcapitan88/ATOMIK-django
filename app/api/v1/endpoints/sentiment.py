"""
Market Sentiment Analysis API Endpoints

Provides comprehensive sentiment analysis for financial markets:
- Market-wide sentiment tracking
- Symbol-specific sentiment analysis  
- Sector sentiment breakdown with rankings
- Historical sentiment trends
- Real-time news sentiment scoring

Integrates with MCP Financial Server for sentiment data collection and analysis.
"""

import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
import httpx
import asyncio
from datetime import datetime

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.feature_flag_service import FeatureFlagService, require_advanced_analytics
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


# Response Models
class SentimentScore(BaseModel):
    score: float = Field(..., description="Sentiment score (-1.0 to 1.0)")
    label: str = Field(..., description="Sentiment label (positive, negative, neutral)")
    confidence: float = Field(..., description="Confidence level (0.0 to 1.0)")


class SentimentDistribution(BaseModel):
    positive: int = Field(..., description="Number of positive articles")
    negative: int = Field(..., description="Number of negative articles")
    neutral: int = Field(..., description="Number of neutral articles")
    total: int = Field(..., description="Total number of articles")


class MarketSentimentResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cached: bool = False
    timestamp: str


class NewsSummaryResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str


class SentimentTrendsResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str


class SectorSentimentResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cached: bool = False
    timestamp: str


class AllSectorsSentimentResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str


# MCP Client
class MCPSentimentClient:
    """Client for communicating with MCP Financial Server sentiment tools."""
    
    def __init__(self):
        self.mcp_server_url = "http://localhost:8001"  # This would come from settings
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call MCP sentiment tool."""
        try:
            # This is a placeholder for MCP integration
            # In practice, you would use the MCP protocol to communicate with the server
            # For now, we'll simulate the calls
            
            if tool_name == "get_market_sentiment":
                return await self._mock_market_sentiment(arguments)
            elif tool_name == "get_news_summary":
                return await self._mock_news_summary(arguments)
            elif tool_name == "get_sentiment_trends":
                return await self._mock_sentiment_trends(arguments)
            elif tool_name == "get_sector_sentiment":
                return await self._mock_sector_sentiment(arguments)
            elif tool_name == "get_all_sectors_sentiment":
                return await self._mock_all_sectors_sentiment(arguments)
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
                
        except Exception as e:
            logger.error(f"MCP tool call failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _mock_market_sentiment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mock market sentiment response."""
        symbol = args.get("symbol")
        timeframe = args.get("timeframe", "1d")
        
        return {
            "success": True,
            "data": {
                "overall_sentiment": {
                    "score": 0.15,
                    "label": "positive",
                    "confidence": 0.72
                },
                "sentiment_distribution": {
                    "positive": 45,
                    "negative": 28,
                    "neutral": 32,
                    "total": 105
                },
                "article_sentiments": [
                    {
                        "score": 0.3,
                        "label": "positive",
                        "confidence": 0.8,
                        "title": "Market shows strong performance in tech sector",
                        "source": "reuters"
                    }
                ],
                "analysis_metadata": {
                    "analyzed_at": datetime.utcnow().isoformat(),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "total_articles_analyzed": 105
                }
            },
            "cached": False,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _mock_news_summary(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mock news summary response."""
        return {
            "success": True,
            "data": {
                "articles": [
                    {
                        "title": "Tech stocks rally on AI optimism",
                        "url": "https://example.com/article1",
                        "published_at": datetime.utcnow().isoformat(),
                        "source": "reuters",
                        "sentiment": {
                            "score": 0.4,
                            "label": "positive",
                            "confidence": 0.85
                        },
                        "relevance_score": 0.9
                    }
                ],
                "total_analyzed": 10,
                "timeframe": "24h",
                "symbol": args.get("symbol")
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _mock_sentiment_trends(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mock sentiment trends response."""
        return {
            "success": True,
            "data": {
                "trends": [
                    {
                        "date": "2025-06-04",
                        "sentiment_score": 0.2,
                        "sentiment_label": "positive",
                        "article_count": 25,
                        "confidence": 0.75
                    }
                ],
                "analysis": {
                    "direction": "improving",
                    "strength": 0.6,
                    "change": 0.05
                },
                "symbol": args.get("symbol"),
                "period_days": args.get("days", 7)
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _mock_sector_sentiment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mock sector sentiment response."""
        sector = args.get("sector", "technology")
        return {
            "success": True,
            "data": {
                "overall_sentiment": {
                    "score": 0.25,
                    "label": "positive",
                    "confidence": 0.78
                },
                "sector_info": {
                    "sector": sector,
                    "timeframe": args.get("timeframe", "1d"),
                    "total_symbols_tracked": 15,
                    "analysis_type": "sector_wide"
                },
                "symbol_breakdown": {
                    "symbol_sentiments": {
                        "AAPL": {
                            "sentiment_score": 0.3,
                            "sentiment_label": "positive",
                            "confidence": 0.8,
                            "article_count": 12
                        }
                    },
                    "top_positive": [["AAPL", {"sentiment_score": 0.3}]],
                    "top_negative": [],
                    "total_symbols_analyzed": 8
                }
            },
            "cached": False,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _mock_all_sectors_sentiment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mock all sectors sentiment response."""
        return {
            "success": True,
            "data": {
                "overall_market_sentiment": {
                    "score": 0.12,
                    "label": "positive",
                    "confidence": 0.68
                },
                "sector_rankings": [
                    {
                        "sector": "technology",
                        "sentiment_score": 0.25,
                        "sentiment_label": "positive",
                        "confidence": 0.78,
                        "article_count": 45
                    },
                    {
                        "sector": "healthcare",
                        "sentiment_score": 0.15,
                        "sentiment_label": "positive",
                        "confidence": 0.65,
                        "article_count": 32
                    }
                ],
                "analysis_metadata": {
                    "timeframe": args.get("timeframe", "1d"),
                    "sectors_analyzed": 10,
                    "analyzed_at": datetime.utcnow().isoformat()
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        }


# Global MCP client instance
mcp_client = MCPSentimentClient()


@router.get(
    "/market",
    response_model=MarketSentimentResponse,
    summary="Get market sentiment analysis",
    description="Get overall market sentiment or symbol-specific sentiment analysis from news sources"
)
@require_advanced_analytics
async def get_market_sentiment(
    symbol: Optional[str] = Query(None, description="Trading symbol for targeted sentiment (optional)"),
    timeframe: str = Query("1d", regex="^(1h|1d|7d|30d)$", description="Time range for analysis"),
    include_social: bool = Query(False, description="Include social sentiment data"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MarketSentimentResponse:
    """Get market sentiment analysis."""
    try:
        logger.info(f"Getting market sentiment for user {current_user.id}, symbol: {symbol}")
        
        result = await mcp_client.call_mcp_tool("get_market_sentiment", {
            "symbol": symbol,
            "timeframe": timeframe,
            "include_social": include_social
        })
        
        return MarketSentimentResponse(**result)
        
    except Exception as e:
        logger.error(f"Error getting market sentiment: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get market sentiment: {str(e)}"
        )


@router.get(
    "/news",
    response_model=NewsSummaryResponse,
    summary="Get recent news with sentiment scores",
    description="Get recent news articles with sentiment analysis and relevance scoring"
)
@require_advanced_analytics
async def get_news_summary(
    symbol: Optional[str] = Query(None, description="Trading symbol for targeted news (optional)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of articles to return"),
    hours_back: int = Query(24, ge=1, le=168, description="How many hours back to search"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> NewsSummaryResponse:
    """Get recent news articles with sentiment scores."""
    try:
        logger.info(f"Getting news summary for user {current_user.id}, symbol: {symbol}")
        
        result = await mcp_client.call_mcp_tool("get_news_summary", {
            "symbol": symbol,
            "limit": limit,
            "hours_back": hours_back
        })
        
        return NewsSummaryResponse(**result)
        
    except Exception as e:
        logger.error(f"Error getting news summary: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get news summary: {str(e)}"
        )


@router.get(
    "/trends",
    response_model=SentimentTrendsResponse,
    summary="Get sentiment trends over time",
    description="Get historical sentiment trends and analysis for market or specific symbols"
)
@require_advanced_analytics
async def get_sentiment_trends(
    symbol: Optional[str] = Query(None, description="Trading symbol for targeted trends (optional)"),
    days: int = Query(7, ge=1, le=30, description="Number of days to analyze"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> SentimentTrendsResponse:
    """Get sentiment trends over time."""
    try:
        logger.info(f"Getting sentiment trends for user {current_user.id}, symbol: {symbol}")
        
        result = await mcp_client.call_mcp_tool("get_sentiment_trends", {
            "symbol": symbol,
            "days": days
        })
        
        return SentimentTrendsResponse(**result)
        
    except Exception as e:
        logger.error(f"Error getting sentiment trends: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get sentiment trends: {str(e)}"
        )


@router.get(
    "/sectors/{sector}",
    response_model=SectorSentimentResponse,
    summary="Get sector sentiment analysis",
    description="Get sentiment analysis for a specific sector with optional individual symbol breakdown"
)
@require_advanced_analytics
async def get_sector_sentiment(
    sector: str,
    timeframe: str = Query("1d", regex="^(1h|1d|7d|30d)$", description="Time range for analysis"),
    include_breakdown: bool = Query(True, description="Include individual symbol breakdowns"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> SectorSentimentResponse:
    """Get sentiment analysis for a specific sector."""
    try:
        # Validate sector
        valid_sectors = [
            "technology", "healthcare", "financial", "energy", "consumer",
            "industrial", "real_estate", "utilities", "telecommunications", "materials"
        ]
        
        if sector not in valid_sectors:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sector '{sector}'. Valid sectors: {valid_sectors}"
            )
        
        logger.info(f"Getting sector sentiment for user {current_user.id}, sector: {sector}")
        
        result = await mcp_client.call_mcp_tool("get_sector_sentiment", {
            "sector": sector,
            "timeframe": timeframe,
            "include_breakdown": include_breakdown
        })
        
        return SectorSentimentResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting sector sentiment: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get sector sentiment: {str(e)}"
        )


@router.get(
    "/sectors",
    response_model=AllSectorsSentimentResponse,
    summary="Get all sectors sentiment analysis",
    description="Get sentiment analysis for all sectors with comparative rankings and market overview"
)
@require_advanced_analytics
async def get_all_sectors_sentiment(
    timeframe: str = Query("1d", regex="^(1h|1d|7d|30d)$", description="Time range for analysis"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> AllSectorsSentimentResponse:
    """Get sentiment analysis for all sectors."""
    try:
        logger.info(f"Getting all sectors sentiment for user {current_user.id}")
        
        result = await mcp_client.call_mcp_tool("get_all_sectors_sentiment", {
            "timeframe": timeframe
        })
        
        return AllSectorsSentimentResponse(**result)
        
    except Exception as e:
        logger.error(f"Error getting all sectors sentiment: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get all sectors sentiment: {str(e)}"
        )


@router.get(
    "/sectors/available",
    summary="Get available sectors for analysis",
    description="Get list of available sectors for sentiment analysis"
)
async def get_available_sectors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, List[str]]:
    """Get available sectors for sentiment analysis."""
    try:
        sectors = [
            "technology", "healthcare", "financial", "energy", "consumer",
            "industrial", "real_estate", "utilities", "telecommunications", "materials"
        ]
        
        return {
            "success": True,
            "data": {
                "sectors": sectors,
                "total_sectors": len(sectors)
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting available sectors: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get available sectors: {str(e)}"
        )