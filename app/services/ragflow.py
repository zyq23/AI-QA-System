from __future__ import annotations

from typing import Any

import httpx


class RagflowError(RuntimeError):
    pass


class RagflowClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: int = 20,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    def _request(self, method: str, path: str, *, json_payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = dict(self._headers())
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        if self._client is not None:
            response = self._client.request(method, path, headers=headers, json=json_payload, params=params)
        else:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                response = client.request(method, path, headers=headers, json=json_payload, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RagflowError(f"RAGFlow request failed: {exc.response.status_code} {exc.response.text}") from exc
        body = response.json()
        if int(body.get("code", -1)) != 0:
            raise RagflowError(f"RAGFlow request failed: {body.get('message') or body}")
        data = body.get("data")
        if data is None:
            raise RagflowError("RAGFlow request returned invalid payload.")
        if not isinstance(data, dict):
            raise RagflowError("RAGFlow request returned invalid payload.")
        return data

    def retrieve_chunks(
        self,
        *,
        question: str,
        dataset_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        page_size: int = 20,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
        top_k: int = 20,
        keyword: bool = True,
        highlight: bool = False,
        use_kg: bool = False,
        toc_enhance: bool = False,
        metadata_condition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question": question,
            "page": 1,
            "page_size": page_size,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight,
            "top_k": top_k,
            "keyword": keyword,
            "highlight": highlight,
            "use_kg": use_kg,
            "toc_enhance": toc_enhance,
        }
        if dataset_ids:
            payload["dataset_ids"] = dataset_ids
        if document_ids:
            payload["document_ids"] = document_ids
        if metadata_condition:
            payload["metadata_condition"] = metadata_condition
        if not payload.get("dataset_ids") and not payload.get("document_ids"):
            raise RagflowError("RAGFlow retrieval requires dataset_ids or document_ids.")
        return self._request("POST", "/api/v1/retrieval", json_payload=payload)

    def list_dataset_documents(self, dataset_id: str, page_size: int = 100) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/api/v1/datasets/{dataset_id}/documents",
                params={"page": page, "page_size": page_size},
            )
            rows = data.get("docs") or data.get("documents") or data.get("data") or []
            if not isinstance(rows, list) or not rows:
                break
            documents.extend([row for row in rows if isinstance(row, dict)])
            if len(rows) < page_size:
                break
            page += 1
        return documents

    def list_document_chunks(self, dataset_id: str, document_id: str, page_size: int = 100) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks",
                params={"page": page, "page_size": page_size},
            )
            rows = data.get("chunks") or []
            if not isinstance(rows, list) or not rows:
                break
            chunks.extend([row for row in rows if isinstance(row, dict)])
            if len(rows) < page_size:
                break
            page += 1
        return chunks
