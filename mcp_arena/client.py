"""HTTP client for the Arena backend API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .env import env_prefixed


class ArenaClient:
    """Thin wrapper over FastAPI control plane routes."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        timeout: float = 600.0,
    ):
        self.base_url = (
            base_url or env_prefixed("CURIA_API_URL", "ARENA_API_URL", "http://127.0.0.1:8001")
        ).rstrip("/")
        self.agent_id = agent_id or env_prefixed("CURIA_AGENT_ID", "ARENA_AGENT_ID")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.agent_id:
            headers["X-Agent-Id"] = self.agent_id
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json,
                headers=self._headers(),
            )
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text

    async def health(self) -> Dict[str, Any]:
        return await self._request("GET", "/")

    async def list_conversations(self) -> List[Dict[str, Any]]:
        return await self._request("GET", "/api/conversations")

    async def create_conversation(self, mode: str = "council") -> Dict[str, Any]:
        return await self._request("POST", "/api/conversations", json={"mode": mode})

    async def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/api/conversations/{conversation_id}")

    async def send_message(
        self,
        conversation_id: str,
        content: str,
        manual_context: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"content": content}
        if manual_context is not None:
            payload["manual_context"] = manual_context
        return await self._request(
            "POST",
            f"/api/conversations/{conversation_id}/message",
            json=payload,
        )

    async def create_turn(
        self,
        conversation_id: str,
        content: str,
        manual_context: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"content": content}
        if manual_context is not None:
            payload["manual_context"] = manual_context
        return await self._request(
            "POST",
            f"/api/conversations/{conversation_id}/turns",
            json=payload,
        )

    async def advance_turn(self, conversation_id: str, turn_id: str) -> Dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/conversations/{conversation_id}/turns/{turn_id}/advance",
        )

    async def get_turn(self, conversation_id: str, turn_id: str) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/conversations/{conversation_id}/turns/{turn_id}",
        )

    async def cancel_turn(self, conversation_id: str, turn_id: str) -> Dict[str, Any]:
        return await self._request(
            "DELETE",
            f"/api/conversations/{conversation_id}/turns/{turn_id}",
        )

    async def list_turns(self, conversation_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/api/conversations/{conversation_id}/turns")

    async def get_index_manifest(
        self,
        conversation_id: Optional[str] = None,
        repo_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if conversation_id:
            params["conversation_id"] = conversation_id
        if repo_root:
            params["repo_root"] = repo_root
        return await self._request("GET", "/api/index_manifest", params=params)

    async def reindex_git(
        self,
        conversation_id: str,
        repo_root: Optional[str] = None,
        include_untracked: Optional[bool] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if repo_root:
            params["repo_root"] = repo_root
        if include_untracked is not None:
            params["include_untracked"] = include_untracked
        return await self._request(
            "POST",
            f"/api/conversations/{conversation_id}/reindex_git",
            params=params,
        )

    async def reindex_snapshot(self, conversation_id: str) -> Dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/conversations/{conversation_id}/reindex",
        )

    async def get_repo_tree(self, conversation_id: str) -> List[Dict[str, Any]]:
        return await self._request("GET", f"/api/conversations/{conversation_id}/repo_tree")

    async def get_file(self, conversation_id: str, path: str) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/conversations/{conversation_id}/file",
            params={"path": path},
        )

    async def search_repo(
        self,
        conversation_id: str,
        query: str,
        limit: int = 3,
    ) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/conversations/{conversation_id}/search",
            params={"q": query, "limit": limit},
        )

    async def resolve_path(
        self,
        conversation_id: str,
        query: str,
        user_query: Optional[str] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"q": query, "limit": limit}
        if user_query:
            params["user_query"] = user_query
        return await self._request(
            "GET",
            f"/api/conversations/{conversation_id}/resolve_path",
            params=params,
        )

    async def get_settings(self) -> Dict[str, Any]:
        return await self._request("GET", "/api/settings")

    async def update_settings(self, **fields: Any) -> Dict[str, Any]:
        return await self._request("POST", "/api/settings", json=fields)

    async def ensure_indexed(
        self,
        conversation_id: str,
        repo_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reindex when manifest reports drift; no-op when fresh."""
        manifest = await self.get_index_manifest(conversation_id, repo_root)
        delta = manifest.get("changed_since_index") or {}
        if delta.get("needs_reindex") or not manifest.get("has_index", True):
            reindex = await self.reindex_git(conversation_id, repo_root=repo_root)
            manifest = await self.get_index_manifest(conversation_id, repo_root)
            return {"reindexed": True, "reindex": reindex, "manifest": manifest}
        return {"reindexed": False, "manifest": manifest}

    async def get_message_execution(
        self,
        conversation_id: str,
        message_index: int,
        include: str = "failures,prompts,cost,context,steps",
    ) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/conversations/{conversation_id}/messages/{message_index}/execution",
            params={"include": include},
        )