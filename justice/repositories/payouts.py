from decimal import Decimal


class PayoutRepository:
    def __init__(self, pool):
        self.pool = pool

    async def totals(self, start, end, attendance_reward):
        rows = await self.pool.fetch(
            """WITH amounts AS (
            SELECT user_id, COUNT(*) * $3::numeric AS amount FROM public.attendance_events
            WHERE created_at >= $1 AND created_at < $2 GROUP BY user_id
            UNION ALL
            SELECT user_id, SUM(total) AS amount FROM public.reports
            WHERE created_at >= $1 AND created_at < $2 GROUP BY user_id)
            SELECT user_id,SUM(amount) AS amount FROM amounts GROUP BY user_id""",
            start,
            end,
            Decimal(attendance_reward),
        )
        return {row["user_id"]: row["amount"] for row in rows}

    async def snapshot(self, guild_id, week, payouts):
        payload = [{**row, "amount": str(row["amount"])} for row in payouts]
        await self.pool.execute(
            """INSERT INTO public.payout_runs(guild_id,week_start,payload)
            VALUES($1,$2,$3) ON CONFLICT DO NOTHING""",
            guild_id,
            week,
            payload,
        )
        return await self.pool.fetchrow(
            "SELECT * FROM public.payout_runs WHERE guild_id=$1 AND week_start=$2", guild_id, week
        )

    async def message_sent(self, guild_id, week, kind, message_id):
        column = {"embed": "embed_message_id", "file": "file_message_id"}[kind]
        await self.pool.execute(
            f"UPDATE public.payout_runs SET {column}=$3 WHERE guild_id=$1 AND week_start=$2",
            guild_id,
            week,
            message_id,
        )

    async def finish(self, guild_id, week):
        await self.pool.execute(
            "UPDATE public.payout_runs SET completed_at=now() WHERE guild_id=$1 AND week_start=$2",
            guild_id,
            week,
        )
