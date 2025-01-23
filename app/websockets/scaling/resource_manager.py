# app/websockets/scaling/resource_manager.py

from typing import Dict, Optional, Any, Set
from datetime import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)

class LoadBalancer:
    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.connections: Dict[str, str] = {}  # connection_id -> node_id
        self._lock = asyncio.Lock()
        self.rate_limits: Dict[str, Dict[str, Any]] = {}
        
        # Configuration
        self.MAX_CONNECTIONS_PER_NODE = 1000
        self.MAX_CONNECTIONS_PER_MINUTE = 60
        self.RATE_LIMIT_WINDOW = 60  # seconds

    async def register_node(self, node_id: str, capacity: int, metadata: Optional[Dict] = None) -> bool:
        """Register a new node with the load balancer"""
        async with self._lock:
            if node_id in self.nodes:
                logger.warning(f"Node {node_id} already registered")
                return True
                
            self.nodes[node_id] = {
                'capacity': capacity,
                'current_load': 0,
                'metadata': metadata or {},
                'connections': set(),
                'last_heartbeat': datetime.utcnow()
            }
            return True

    async def get_best_node(self) -> Optional[str]:
        """Get the best node for a new connection using least connections algorithm"""
        async with self._lock:
            available_nodes = [
                (node_id, info) for node_id, info in self.nodes.items()
                if info['current_load'] < info['capacity']
            ]
            
            if not available_nodes:
                return None
                
            # Use least connections algorithm
            return min(
                available_nodes,
                key=lambda x: x[1]['current_load'] / x[1]['capacity']
            )[0]

    async def register_connection(self, connection_id: str, node_id: str) -> bool:
        """Register a new connection to a node"""
        try:
            async with self._lock:
                if node_id not in self.nodes:
                    logger.error(f"Node {node_id} not found")
                    return False

                node = self.nodes[node_id]
                if node['current_load'] >= node['capacity']:
                    logger.error(f"Node {node_id} at capacity")
                    return False

                node['current_load'] += 1
                node['connections'].add(connection_id)
                self.connections[connection_id] = node_id
                return True

        except Exception as e:
            logger.error(f"Error registering connection: {str(e)}")
            return False

    async def release_connection(self, connection_id: str) -> None:
        """Release a connection from its node"""
        async with self._lock:
            node_id = self.connections.pop(connection_id, None)
            if node_id and node_id in self.nodes:
                node = self.nodes[node_id]
                node['current_load'] = max(0, node['current_load'] - 1)
                node['connections'].discard(connection_id)

    def get_node_status(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a node"""
        if node_id not in self.nodes:
            return None
            
        node = self.nodes[node_id]
        return {
            'current_load': node['current_load'],
            'capacity': node['capacity'],
            'connection_count': len(node['connections']),
            'last_heartbeat': node['last_heartbeat'].isoformat(),
            'metadata': node['metadata']
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get overall load balancer statistics"""
        return {
            'total_nodes': len(self.nodes),
            'total_connections': len(self.connections),
            'nodes': {
                node_id: self.get_node_status(node_id)
                for node_id in self.nodes
            }
        }

class ResourceManager:
    def __init__(self):
        self.load_balancer = LoadBalancer()
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the resource manager"""
        if self._initialized:
            return True
            
        async with self._lock:
            try:
                # Register default node
                await self.load_balancer.register_node(
                    "default_node",
                    capacity=1000,
                    metadata={"type": "default"}
                )
                self._initialized = True
                return True
            except Exception as e:
                logger.error(f"Failed to initialize resource manager: {str(e)}")
                return False

    async def register_connection(
        self,
        client_host: str,
        client_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Register a new connection"""
        try:
            # Get best node
            node_id = await self.load_balancer.get_best_node()
            if not node_id:
                logger.error("No available nodes")
                return None

            # Register connection with load balancer
            success = await self.load_balancer.register_connection(client_id, node_id)
            if not success:
                return None

            return node_id

        except Exception as e:
            logger.error(f"Error registering connection: {str(e)}")
            return None

    async def release_connection(self, client_id: str) -> None:
        """Release a connection"""
        try:
            await self.load_balancer.release_connection(client_id)
        except Exception as e:
            logger.warning(f"Error releasing connection {client_id}: {str(e)}")
            
# Create singleton instance
resource_manager = ResourceManager()