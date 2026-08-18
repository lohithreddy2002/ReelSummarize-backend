"""
Ranking and pagination for unified search (Phase 2).
"""
from datetime import datetime, timezone

from domain.models import ContentItem
from ports.persistence import PersistencePort


class SearchService:
    def __init__(self, persistence: PersistencePort) -> None:
        self._p = persistence

    async def search_items(
        self,
        owner_user_id: str,
        *,
        q: str | None = None,
        smart: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ContentItem]:
        candidates = await self._p.search_content(owner_user_id, q=q, smart=smart, max_results=500)
        ranked = self._rank(candidates, q)
        return ranked[offset : offset + limit]

    def _rank(self, items: list[ContentItem], q: str | None) -> list[ContentItem]:
        qq = (q or "").strip().lower()
        scored: list[tuple[float, float, ContentItem]] = []
        now = datetime.now(timezone.utc)
        for c in items:
            score = 0.0
            if c.status == "ready":
                score += 2.0
            if qq:
                title = (c.title_generated or c.title_original or "").lower()
                summ = (c.summary_text or "").lower()
                tag_blob = " ".join((c.semantic_tags or []) + (c.mood_tags or [])).lower()
                if qq in title:
                    score += 12.0
                elif title.startswith(qq):
                    score += 8.0
                if qq in summ:
                    score += 6.0
                if qq in tag_blob:
                    score += 4.0
            ts = c.created_at.timestamp() if c.created_at.tzinfo else c.created_at.replace(tzinfo=timezone.utc).timestamp()
            age_days = max(0.0, (now.timestamp() - ts) / 86400.0)
            score += max(0.0, 4.0 - min(age_days, 14.0) * 0.15)
            scored.append((score, c.created_at.timestamp(), c))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [x[2] for x in scored]
