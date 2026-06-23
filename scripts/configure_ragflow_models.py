from __future__ import annotations

import logging
import os
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ragflow_root = os.path.join(root, "ragflow")
    if ragflow_root not in sys.path:
        sys.path.insert(0, ragflow_root)

    os.environ.setdefault("DOC_ENGINE", "infinity")
    os.environ.setdefault("COMPOSE_PROFILES", "infinity,tei-cpu,cpu")

    from common import settings
    from common.constants import LLMType
    from api.db.services.tenant_llm_service import TenantLLMService
    from api.db.services.user_service import TenantService
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.init_data import fix_empty_tenant_model_id

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings.init_settings()

    configured_name = settings.EMBEDDING_MDL or "BAAI/bge-m3"
    embedding_name, parsed_factory = TenantLLMService.split_model_name_and_factory(configured_name)
    embedding_factory = parsed_factory or settings.EMBEDDING_CFG.get("factory") or "Builtin"
    embedding_base = settings.EMBEDDING_CFG.get("base_url") or "http://127.0.0.1:6380"
    embedding_api_key = settings.EMBEDDING_CFG.get("api_key") or ""
    embedding_max_tokens = 8192
    embedding_identifier = f"{embedding_name}@{embedding_factory}"

    tenants = list(TenantService.get_all())
    if not tenants:
        logging.warning("No tenants found, skip tenant model configuration.")
        return 0

    for tenant in tenants:
        tenant_dict = tenant.to_dict()
        tenant_id = tenant_dict["id"]
        logging.info("Configure tenant models for tenant=%s name=%s", tenant_id, tenant_dict.get("name"))

        tenant_model = TenantLLMService.get_api_key(tenant_id, embedding_identifier, LLMType.EMBEDDING.value)
        if not tenant_model:
            TenantLLMService.save(
                tenant_id=tenant_id,
                llm_factory=embedding_factory,
                llm_name=embedding_name,
                model_type=LLMType.EMBEDDING.value,
                api_key=embedding_api_key,
                api_base=embedding_base,
                max_tokens=embedding_max_tokens,
                used_tokens=0,
                status="1",
            )
            tenant_model = TenantLLMService.get_api_key(tenant_id, embedding_identifier, LLMType.EMBEDDING.value)
            logging.info("Inserted tenant embedding model for tenant=%s", tenant_id)

        update_dict: dict[str, object] = {}
        if tenant_dict.get("embd_id") != embedding_identifier:
            update_dict["embd_id"] = embedding_identifier
        if tenant_model and tenant_dict.get("tenant_embd_id") != tenant_model.id:
            update_dict["tenant_embd_id"] = tenant_model.id

        if update_dict:
            TenantService.update_by_id(tenant_id, update_dict)
            logging.info("Updated tenant=%s with %s", tenant_id, update_dict)

        kb_updates = {"embd_id": embedding_identifier}
        if tenant_model:
            kb_updates["tenant_embd_id"] = tenant_model.id
        KnowledgebaseService.filter_update([KnowledgebaseService.model.tenant_id == tenant_id], kb_updates)
        logging.info("Updated datasets for tenant=%s with %s", tenant_id, kb_updates)

    fix_empty_tenant_model_id()
    logging.info("RAGFlow tenant embedding configuration finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
