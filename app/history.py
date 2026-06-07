import logging
from datetime import datetime, timedelta, timezone

from app.config import config

logger = logging.getLogger(__name__)


def prune_old_history():
    """Delete check_history rows older than HISTORY_RETENTION_DAYS."""
    from app.database import get_db_connection

    conn = get_db_connection()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.history_retention_days)
        cursor = conn.execute(
            "DELETE FROM check_history WHERE checked_at < ?",
            (cutoff.isoformat(),)
        )
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Pruned {cursor.rowcount} old check_history rows")
    finally:
        conn.close()
