"""关联关系 — 自动建立记忆间的联系"""

from miniclaw.memory.store import MemoryStore, Memory


def auto_link_related(store: MemoryStore, new_memory: Memory, recent_memories: list[Memory]):
    """为新记忆自动建立关联"""
    for existing in recent_memories:
        if existing.id == new_memory.id:
            continue

        # 共同实体 → relates_to
        common_entities = set(new_memory.entities) & set(existing.entities)
        if common_entities:
            store.add_relation(new_memory.id, existing.id, "relates_to", strength=len(common_entities) * 0.3)
            store.add_relation(existing.id, new_memory.id, "relates_to", strength=len(common_entities) * 0.3)

        # 共同标签 → relates_to
        common_tags = set(new_memory.tags) & set(existing.tags)
        if common_tags and not common_entities:  # 避免重复关联
            store.add_relation(new_memory.id, existing.id, "relates_to", strength=len(common_tags) * 0.2)
            store.add_relation(existing.id, new_memory.id, "relates_to", strength=len(common_tags) * 0.2)

        # 同类型且内容相似 → similar
        if new_memory.memory_type == existing.memory_type and new_memory.tags and existing.tags:
            tag_overlap = len(set(new_memory.tags) & set(existing.tags)) / max(len(set(new_memory.tags) | set(existing.tags)), 1)
            if tag_overlap > 0.6:
                store.add_relation(new_memory.id, existing.id, "similar", strength=tag_overlap)
                store.add_relation(existing.id, new_memory.id, "similar", strength=tag_overlap)
