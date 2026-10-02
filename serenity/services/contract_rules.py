from serenity.config import get_settings

settings = get_settings()
MAX_ACTIVE_SLOTS = 5
HIGH_STAFF_ROLE_ID = settings.high_staff_role_id
ROLE_PRIORITY = {role_id: rank for rank, role_id in enumerate(settings.rank_role_ids, start=1)}
ROLE_PRIORITY[HIGH_STAFF_ROLE_ID] = len(settings.rank_role_ids) + 1
