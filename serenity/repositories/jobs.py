from serenity.database import get_database


class JobRepository:
    def __init__(self, pool=None):
        self.pool = pool if pool is not None else get_database().pool

    async def schedule(self, kind, key, payload, due_at, expires_at):
        await self.pool.execute(
            """INSERT INTO public.jobs(kind,dedupe_key,payload,due_at,expires_at)
            VALUES($1,$2,$3,$4,$5) ON CONFLICT(kind,dedupe_key) DO NOTHING""",
            kind,
            str(key),
            payload,
            due_at,
            expires_at,
        )

    async def claim(self):
        return await self.pool.fetchrow("""WITH candidate AS (
            SELECT id FROM public.jobs WHERE completed_at IS NULL AND due_at<=now()
            AND expires_at>now() AND (lease_until IS NULL OR lease_until<now())
            ORDER BY due_at FOR UPDATE SKIP LOCKED LIMIT 1)
            UPDATE public.jobs j SET lease_until=now()+interval '5 minutes',attempts=attempts+1
            FROM candidate c WHERE j.id=c.id RETURNING j.*""")

    async def complete(self, job_id):
        await self.pool.execute(
            "UPDATE public.jobs SET completed_at=now(),lease_until=NULL WHERE id=$1", job_id
        )

    async def retry(self, job_id, error_type):
        await self.pool.execute(
            """UPDATE public.jobs SET lease_until=NULL,
            due_at=now()+interval '1 minute',last_error=$2 WHERE id=$1""",
            job_id,
            error_type,
        )
