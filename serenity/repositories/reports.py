from datetime import datetime, timezone


class ReportRepository:
    def __init__(self, pool):
        self.pool = pool

    async def create(
        self,
        *,
        interaction_id,
        nickname,
        static_id,
        category,
        quantity,
        total,
        proof,
        user_id,
        username,
    ):
        return await self.pool.fetchval(
            """INSERT INTO public.reports
            (created_at,nickname,static_id,category,quantity,total,proof,user_id,username,interaction_id)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT(interaction_id) DO NOTHING RETURNING id""",
            datetime.now(timezone.utc),
            nickname,
            static_id,
            category,
            quantity,
            total,
            proof,
            user_id,
            username,
            interaction_id,
        )
