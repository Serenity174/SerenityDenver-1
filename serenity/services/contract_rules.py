from serenity.config import get_settings
from serenity.services.settings import option


def active_slots():
    return option("contract_slots", 5)


def role_priority():
    settings = get_settings()
    priorities = {role_id: rank for rank, role_id in enumerate(settings.rank_role_ids, start=1)}
    priorities[settings.high_staff_role_id] = len(settings.rank_role_ids) + 1
    return priorities
