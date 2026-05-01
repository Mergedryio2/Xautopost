from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Bangkok")


def now_local() -> datetime:
    """Bangkok local time (UTC+7) as naive datetime."""
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


# Backward-compat alias — historically named utcnow but now returns Bangkok local.
# All call sites can keep using utcnow; new code should prefer now_local.
utcnow = now_local
