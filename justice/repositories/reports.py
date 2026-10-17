from datetime import datetime, timedelta, timezone


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
        publication=None,
    ):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                record_id = await self._create(
                    conn,
                    interaction_id,
                    nickname,
                    static_id,
                    category,
                    quantity,
                    total,
                    proof,
                    user_id,
                    username,
                )
                if record_id is not None and publication:
                    publication = {**publication, "report_id": record_id}
                    publication["embed"] = {
                        **publication["embed"],
                        "footer": {"text": f"ID записи: {record_id}"},
                    }
                    now = datetime.now(timezone.utc)
                    await conn.execute(
                        "INSERT INTO public.jobs(kind,dedupe_key,payload,due_at,expires_at) "
                        "VALUES('report_publication',$1,$2,$3,$4) ON CONFLICT DO NOTHING",
                        str(record_id),
                        publication,
                        now,
                        now + timedelta(days=30),
                    )
                return record_id

    async def _create(
        self,
        conn,
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
        return await conn.fetchval(
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
