"""
WebSocket Connection Manager

Manages WebSocket connections for real-time user notifications.
Enables insight delivery, chat streaming, and other real-time features.
"""
from typing import Dict, Any, Optional
from fastapi import WebSocket
import asyncio
import json

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time user notifications.
    
    Features:
    - Track active connections per user
    - Broadcast to specific users
    - Handle connection lifecycle
    """
    
    def __init__(self):
        # Map user_id -> list of active WebSocket connections
        self._connections: Dict[int, list[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        """Accept WebSocket connection and register for user."""
        await websocket.accept()
        
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(websocket)
        
        logger.info(f"[ConnectionManager] User {user_id} connected (total: {len(self._connections.get(user_id, []))})")
    
    async def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        """Remove WebSocket connection for user."""
        async with self._lock:
            if user_id in self._connections:
                try:
                    self._connections[user_id].remove(websocket)
                    if not self._connections[user_id]:
                        del self._connections[user_id]
                except ValueError:
                    pass
        
        logger.info(f"[ConnectionManager] User {user_id} disconnected")
    
    async def send_to_user(self, user_id: int, message: Dict[str, Any]) -> int:
        """
        Send a message to all connections for a specific user.
        
        Args:
            user_id: Target user ID
            message: Message payload (will be JSON serialized)
            
        Returns:
            Number of connections the message was sent to
        """
        sent_count = 0
        
        async with self._lock:
            connections = self._connections.get(user_id, []).copy()
        
        for websocket in connections:
            try:
                await websocket.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[ConnectionManager] Failed to send to user {user_id}: {e}")
                # Remove dead connection
                await self.disconnect(websocket, user_id)
        
        return sent_count
    
    async def broadcast(self, message: Dict[str, Any]) -> int:
        """
        Broadcast a message to all connected users.
        
        Args:
            message: Message payload
            
        Returns:
            Total number of connections the message was sent to
        """
        sent_count = 0
        
        async with self._lock:
            all_connections = [
                (user_id, ws) 
                for user_id, ws_list in self._connections.items() 
                for ws in ws_list
            ]
        
        for user_id, websocket in all_connections:
            try:
                await websocket.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[ConnectionManager] Broadcast failed for user {user_id}: {e}")
                await self.disconnect(websocket, user_id)
        
        return sent_count
    
    def is_user_connected(self, user_id: int) -> bool:
        """Check if a user has any active connections."""
        return user_id in self._connections and len(self._connections[user_id]) > 0
    
    def get_connected_users(self) -> list[int]:
        """Get list of all connected user IDs."""
        return list(self._connections.keys())
    
    def get_connection_count(self, user_id: Optional[int] = None) -> int:
        """
        Get number of active connections.
        
        Args:
            user_id: Optional user ID to count for specific user
            
        Returns:
            Connection count (for user or total)
        """
        if user_id is not None:
            return len(self._connections.get(user_id, []))
        return sum(len(conns) for conns in self._connections.values())


# Global instance
_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get or create the global ConnectionManager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
        logger.info("[OK] ConnectionManager initialized")
    return _connection_manager


def init_connection_manager() -> ConnectionManager:
    """Initialize and return the global ConnectionManager."""
    global _connection_manager
    _connection_manager = ConnectionManager()
    logger.info("[OK] ConnectionManager initialized")
    return _connection_manager
