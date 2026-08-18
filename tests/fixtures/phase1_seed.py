"""
Seed data for tests and local smoke runs (in-memory persistence).
"""
from adapters.persistence.in_memory import InMemoryPersistenceAdapter
from application.content_service import ContentService
from domain.models import Location


async def seed_sample_content(
    persistence: InMemoryPersistenceAdapter,
    *,
    owner_user_id: str = "seed_user",
    source_url: str = "https://www.instagram.com/reel/seed123",
) -> tuple[str, str]:
    """Create one content row, one job, and one map location. Returns (content_id, job_id)."""
    service = ContentService(persistence)
    created = await service.ingest_content(owner_user_id, source_url)
    content = created["content"]
    job = created["job"]
    content_id = content.id
    job_id = job.id
    await persistence.update_content(
        content_id,
        owner_user_id,
        status="ready",
        title_original="Seed title",
        title_generated="Seed Generated Title",
        summary_text="Seed summary for fixture.",
        summary_method="metadata_analysis",
        thumbnail_url="https://example.com/thumb.jpg",
    )
    await persistence.upsert_locations(
        content_id,
        [
            Location(
                content_id=content_id,
                name="Mumbai",
                display_name="Mumbai, India",
                lat=19.076,
                lng=72.8777,
                geocoded=True,
            )
        ],
    )
    return content_id, job_id
