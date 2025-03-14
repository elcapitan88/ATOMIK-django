# app/services/railway_server_manager.py

import os
import logging
import aiohttp
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.broker import BrokerAccount, BrokerCredentials

logger = logging.getLogger(__name__)

class RailwayServerManager:
    """
    Service for managing IBEam server instances on Railway.
    Handles provisioning, monitoring, and lifecycle management of
    per-user IBEam servers.
    """
    
    def __init__(self):
        self.api_key = os.environ.get("RAILWAY_API_KEY")
        self.api_url = "https://backboard.railway.app/graphql"
        self.template_id = os.environ.get("RAILWAY_IBEARMY_TEMPLATE_ID")
        self.project_id = os.environ.get("RAILWAY_PROJECT_ID")
        
        if not self.api_key:
            logger.warning("RAILWAY_API_KEY environment variable not set")
        if not self.template_id:
            logger.warning("RAILWAY_IBEARMY_TEMPLATE_ID environment variable not set")
        if not self.project_id:
            logger.warning("RAILWAY_PROJECT_ID environment variable not set")
    
    async def _make_api_request(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request to the Railway GraphQL API"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "query": query,
            "variables": variables or {}
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.api_url, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Railway API error: {error_text}")
                    raise HTTPException(status_code=500, detail="Error communicating with Railway API")
                
                data = await response.json()
                if "errors" in data:
                    logger.error(f"Railway GraphQL errors: {data['errors']}")
                    raise HTTPException(status_code=500, detail=f"Railway API error: {data['errors'][0]['message']}")
                
                return data["data"]
    
    async def provision_server(self, db: Session, user: User, ib_username: str, ib_password: str) -> Dict[str, Any]:
        """Provision a new IBEam server instance by cloning an existing service"""
        # Generate a unique API key for this server
        api_key = str(uuid.uuid4())
        
        # Generate a unique name for this service
        service_name = f"ibearmy-user-{user.id}-{uuid.uuid4().hex[:8]}"
        
        # Create service by cloning your template service
        clone_query = """
        mutation CloneService($input: ServiceCloneInput!) {
            serviceClone(input: $input) {
                id
                name
                projectId
                createdAt
            }
        }
        """
        
        variables = {
            "input": {
                "name": service_name,
                # Use your base service ID here - the one that is already deployed
                "serviceId": "b63ea1d4-a2f5-4507-9a90-f65cbddee7c2",
                "variables": [
                    {"name": "USER_ID", "value": str(user.id)},
                    {"name": "IB_USERNAME", "value": ib_username},
                    {"name": "IB_PASSWORD", "value": ib_password},
                    {"name": "API_KEY", "value": api_key},
                    {"name": "ENVIRONMENT", "value": "production"}
                ]
            }
        }
        
        try:
            # Call Railway API to create service using the clone mutation
            result = await self._make_api_request(clone_query, variables)
            service = result.get("serviceClone", {})
            
            if not service.get("id"):
                raise HTTPException(status_code=500, detail="Failed to provision IBEam server")
            
            # Add server information to database
            # In a real implementation, you would add a model for IBEam servers
            # and track the Railway service ID, API key, and status
            
            # For now, add it to broker account
            broker_account = BrokerAccount(
                user_id=user.id,
                broker_id="interactivebrokers",
                account_id=f"ib_{ib_username}",
                name="Interactive Brokers Account",
                environment="demo",
                is_active=True,
                status="provisioning",
                last_connected=datetime.utcnow(),
                error_message=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(broker_account)
            db.flush()
            
            # Store credentials
            broker_credentials = BrokerCredentials(
                broker_id="interactivebrokers",
                account_id=broker_account.id,
                credential_type="railway_service",
                access_token=api_key,
                is_valid=True,
                # Store Railway details as JSON in a separate field
                custom_data=json.dumps({
                    "railway_service_id": service.get("id"),
                    "railway_service_name": service_name,
                    "api_key": api_key,
                    "status": "provisioning"
                }),
                expires_at=datetime.utcnow() + timedelta(days=90),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(broker_credentials)
            db.commit()
            
            logger.info(f"Provisioned IBEam server for user {user.id}: {service_name}")
            
            return {
                "status": "provisioning",
                "account_id": broker_account.account_id,
                "message": "IBEam server is being provisioned",
                "service_id": service.get("id"),
                "service_name": service_name
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error provisioning IBEam server: {str(e)}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to provision IBEam server: {str(e)}"
            )
    
    async def get_server_status(self, railway_service_id: str) -> Dict[str, Any]:
        """Get the status of a Railway service"""
        query = """
        query GetService($id: ID!) {
            service(id: $id) {
                id
                name
                status
                url
                createdAt
                updatedAt
            }
        }
        """
        
        variables = {
            "id": railway_service_id
        }
        
        result = await self._make_api_request(query, variables)
        return result.get("service", {})
    
    async def stop_server(self, railway_service_id: str) -> bool:
        """Stop a Railway service"""
        query = """
        mutation StopService($id: ID!) {
            serviceStop(id: $id) {
                id
                status
            }
        }
        """
        
        variables = {
            "id": railway_service_id
        }
        
        result = await self._make_api_request(query, variables)
        return "serviceStop" in result
    
    async def start_server(self, railway_service_id: str) -> bool:
        """Start a Railway service"""
        query = """
        mutation StartService($id: ID!) {
            serviceStart(id: $id) {
                id
                status
            }
        }
        """
        
        variables = {
            "id": railway_service_id
        }
        
        result = await self._make_api_request(query, variables)
        return "serviceStart" in result
    
    async def delete_server(self, railway_service_id: str) -> bool:
        """Delete a Railway service"""
        query = """
        mutation DeleteService($id: ID!) {
            serviceDelete(id: $id) {
                id
            }
        }
        """
        
        variables = {
            "id": railway_service_id
        }
        
        result = await self._make_api_request(query, variables)
        return "serviceDelete" in result

# Create a singleton instance
railway_server_manager = RailwayServerManager()