#!/usr/bin/env python3
"""
Reset stuck extraction jobs (``processing`` with old ``updated_at``) to ``queued``.

Run from ``backend/`` with the same env as the API (Supabase keys when using Supabase)::

    python scripts/backfill_stuck_extractions.py

Env:
  STUCK_MINUTES — default ``90``
  DRY_RUN=1 — print job ids only, no updates
"""
from __future__ import annotations

import asyncio
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from composition_root import get_persistence  # noqa: E402


async def main() -> None:
    stuck_min = int(os.getenv("STUCK_MINUTES", "90"))
    dry = os.getenv("DRY_RUN", "").strip() in ("1", "true", "yes")
    p = get_persistence()
    ids = await p.list_stuck_extraction_job_ids(older_than_minutes=stuck_min, limit=500)
    print(f"found {len(ids)} stuck job(s) (processing, updated_at > {stuck_min}m ago)")
    if not ids:
        return
    print("job_ids:", ", ".join(ids[:20]) + ("..." if len(ids) > 20 else ""))
    if dry:
        print("DRY_RUN=1 — no updates")
        return
    for jid in ids:
        ok = await p.admin_force_requeue_job(jid)
        print("requeue", jid, "->", ok)


if __name__ == "__main__":
    asyncio.run(main())
