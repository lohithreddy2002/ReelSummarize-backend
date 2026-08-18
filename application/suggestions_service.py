"""
Phase 2 suggestions derived from persisted content (tags, titles).
"""
from ports.persistence import PersistencePort


class SuggestionsService:
    def __init__(self, persistence: PersistencePort) -> None:
        self._p = persistence

    async def suggestions(self, owner_user_id: str, q: str | None) -> dict:
        rows = await self._p.search_content(owner_user_id, q=q, smart=None, max_results=80)
        tags: set[str] = set()
        titles: list[str] = []
        for c in rows:
            if c.title_generated:
                titles.append(c.title_generated)
            for t in c.semantic_tags or []:
                if t:
                    tags.add(str(t).strip())
            for t in c.mood_tags or []:
                if t:
                    tags.add(str(t).strip())
        titles = titles[:15]
        tag_list = sorted(tags)[:25]
        return {"success": True, "tags": tag_list, "titles": titles}
