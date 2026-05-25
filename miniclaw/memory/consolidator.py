"""后台巩固 — 反思、合并、验证、衰减"""

from miniclaw.memory.store import MemoryStore, Memory
from miniclaw.memory.decay import calculate_priority, should_suppress, should_archive
from miniclaw.memory.relations import auto_link_related


class Consolidator:
    """对话结束后的后台巩固"""

    def __init__(self, store: MemoryStore):
        self.store = store

    def consolidate(self):
        """执行一轮巩固"""
        changes = {"reflected": 0, "merged": 0, "decayed": 0, "rules_created": 0}

        # 1. 即时反思：未处理的 information 升级条件
        changes["reflected"] = self._reflect()

        # 2. 相似经验合并
        changes["merged"] = self._merge_similar()

        # 3. 衰减计算
        changes["decayed"] = self._apply_decay()

        # 4. 规则提升：验证通过且多次使用的 Knowledge 可压缩为反射规则
        changes["rules_created"] = self._promote_to_rules()

        return changes

    def _reflect(self) -> int:
        """反思：给有因果关系线索的记忆升级"""
        count = 0
        # 所有 verify_count > 0 的 unverified 记忆升级为 verified
        all_memories = self.store.list_all(limit=200)
        for mem in all_memories:
            if mem.status == "unverified" and mem.apply_count >= 1:
                self.store.update(mem.id, status="verified", verify_count=1)
                count += 1
        return count

    def _merge_similar(self) -> int:
        """合并相似经验：相同标签+实体的 information/data → knowledge"""
        count = 0
        all_memories = self.store.list_all(limit=200)

        # 按标签组聚合（data 和 information 都参与合并）
        tag_groups: dict[str, list[Memory]] = {}
        for mem in all_memories:
            if mem.dikw_level not in ("information", "data"):
                continue
            key = ",".join(sorted(mem.tags + [mem.memory_type]))
            tag_groups.setdefault(key, []).append(mem)

        for key, group in tag_groups.items():
            if len(group) < 2:
                continue

            # 有2+条相似经验 → 合并为一条 knowledge
            merged_summary = self._merge_summaries(group)
            merged_content = "\n---\n".join(f"经验{i+1}: {m.summary}" for i, m in enumerate(group))

            merged = Memory(
                content=merged_content,
                summary=merged_summary,
                memory_type=group[0].memory_type,
                dikw_level="knowledge",
                importance=max(m.importance for m in group) + 0.1,
                tags=list(set(t for m in group for t in m.tags)),
                entities=list(set(e for m in group for e in m.entities)),
                apply_count=sum(m.apply_count for m in group),
                status="unverified",
            )

            self.store.save(merged)

            # 标记旧记忆被替代
            for old in group:
                self.store.supersede(old.id, merged.id)
                self.store.add_relation(merged.id, old.id, "supersedes")

            count += 1

        return count

    def _merge_summaries(self, memories: list[Memory]) -> str:
        """合并多条记忆的摘要"""
        if len(memories) == 1:
            return memories[0].summary

        # 简单合并：取共同标签 + "等N条经验"
        common_tags = set(memories[0].tags)
        for m in memories[1:]:
            common_tags &= set(m.tags)

        if common_tags:
            return f"关于{'+'.join(common_tags)}的{len(memories)}条经验合并"
        else:
            return f"{len(memories)}条相关经验合并"

    def _apply_decay(self) -> int:
        """应用衰减：软遗忘和归档"""
        count = 0
        all_memories = self.store.list_all(limit=200)

        for mem in all_memories:
            if should_archive(mem) and mem.retrieval_suppressed < 2:
                self.store.update(mem.id, retrieval_suppressed=2, status="archived")
                count += 1
            elif should_suppress(mem) and mem.retrieval_suppressed < 1:
                self.store.update(mem.id, retrieval_suppressed=1)
                count += 1

        return count

    def _promote_to_rules(self) -> int:
        """将验证通过且多次使用的 Knowledge 压缩为反射规则"""
        count = 0
        all_memories = self.store.list_all(limit=200)

        for mem in all_memories:
            if mem.dikw_level == "knowledge" and mem.status == "verified" and mem.apply_count >= 3:
                # 生成规则：从标签和实体提取关键词
                pattern = ",".join(mem.tags + mem.entities)
                if not pattern:
                    continue

                rule_id = f"rule_{mem.id}"
                self.store.save_rule(
                    rule_id=rule_id,
                    pattern=pattern,
                    action="direct_answer",
                    response=mem.summary,
                    source_memory_id=mem.id,
                )

                # 标记记忆升级为 wisdom
                self.store.update(mem.id, dikw_level="wisdom")
                count += 1

        return count
