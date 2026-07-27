"""
Persistence for backend strategy campaigns (Phase-3 WS3) — a thin Prisma seam over
``Campaign``, mirroring ``db/backtest_repository.py``.

One row is a campaign: the posted grid ``spec`` (stored verbatim as JSON so the
expansion is reproducible/auditable), its ``status``, ``concurrency``, and
denormalised progress counters (``total`` / ``completed`` / ``failed``) the execution
queue (WS3 Slice 2) bumps as members finish. Member strategies link back via
``Strategy.campaign_id``. Tests inject ``FakeCampaignRepository``.
"""

from __future__ import annotations

import logging

from db.serde import enum_value as _enum_value
from db.serde import iso as _iso

logger = logging.getLogger(__name__)


class PrismaCampaignRepository:
    """Prisma-backed implementation. Imports the generated client lazily."""

    async def create(self, params: dict) -> dict:
        from prisma import Json

        from db.client import get_db

        db = await get_db()
        data = dict(params)
        if "spec" in data and data["spec"] is not None:
            data["spec"] = Json(data["spec"])
        record = await db.campaign.create(data=data)
        return self._to_dict(record)

    async def get(self, campaign_id: str) -> dict | None:
        from db.client import get_db

        db = await get_db()
        record = await db.campaign.find_unique(where={"id": campaign_id})
        return self._to_dict(record) if record is not None else None

    async def list(self) -> list[dict]:
        from db.client import get_db

        import config

        db = await get_db()
        records = await db.campaign.find_many(
            where={"data_source": config.SCAN_DATA_SOURCE},
            order={"created_at": "desc"},
        )
        return [self._to_dict(r) for r in records]

    async def list_running(self) -> list[dict]:
        """Campaigns left RUNNING (across every data source) — for startup resume."""
        from db.client import get_db

        db = await get_db()
        records = await db.campaign.find_many(where={"status": "RUNNING"})
        return [self._to_dict(r) for r in records]

    async def update(self, campaign_id: str, data: dict) -> dict | None:
        from prisma import Json
        from prisma.errors import RecordNotFoundError

        from db.client import get_db

        db = await get_db()
        payload = dict(data)
        if "spec" in payload and payload["spec"] is not None:
            payload["spec"] = Json(payload["spec"])
        try:
            record = await db.campaign.update(where={"id": campaign_id}, data=payload)
        except RecordNotFoundError:
            return None
        return self._to_dict(record) if record is not None else None

    async def delete(self, campaign_id: str) -> bool:
        from prisma.errors import RecordNotFoundError

        from db.client import get_db

        db = await get_db()
        try:
            # ON DELETE SET NULL detaches members; the runs themselves survive.
            await db.campaign.delete(where={"id": campaign_id})
        except RecordNotFoundError:
            return False
        return True

    @staticmethod
    def _to_dict(r) -> dict:
        return {
            "id": r.id,
            "name": r.name,
            "exchange": _enum_value(r.exchange),
            "data_source": r.data_source,
            "status": _enum_value(r.status),
            "spec": r.spec,
            "concurrency": r.concurrency,
            "total": r.total,
            "completed": r.completed,
            "failed": r.failed,
            "created_at": _iso(r.created_at),
            "updated_at": _iso(r.updated_at),
            "started_at": _iso(r.started_at),
            "ended_at": _iso(r.ended_at),
        }


_repo: PrismaCampaignRepository | None = None


def get_campaign_repository() -> PrismaCampaignRepository:
    """Return the process-wide campaign repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaCampaignRepository()
    return _repo
