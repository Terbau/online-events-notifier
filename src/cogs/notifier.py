import asyncio
import datetime
import traceback

from discord.ext import commands


class NotifierCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cached_tzinfo = None
        self.updater_task = asyncio.create_task(self.updater_runner())

    async def cog_unload(self):
        self.updater_task.cancel()

    async def updater_runner(self):
        try:
            while True:
                await self.updater()
                await asyncio.sleep(5 * 60)
        except Exception:
            traceback.print_exc()

    async def _insert_event(self, event, exists: bool = False):
        async with self.bot.pool.acquire() as conn:
            if not exists:
                await conn.execute(
                    'INSERT INTO events (id, title, description, start_date, end_date, organizer, last_updated) '
                    'VALUES ($1, $2, $3, $4, $5, $6, $7)',
                    event['id'],
                    event['title'],
                    event['description'],
                    event['start_date'],
                    event['end_date'],
                    event['organizer'],
                    datetime.datetime.now(),
                )
            else:
                await conn.execute(
                    'UPDATE events SET title=$1, description=$2, start_date=$3, end_date=$4, organizer=$5, last_updated=$6 '
                    'WHERE id=$7',
                    event['title'],
                    event['description'],
                    event['start_date'],
                    event['end_date'],
                    event['organizer'],
                    datetime.datetime.now(),
                    event['id'],
                )

    async def updater(self):
        events = await self.fetch_events()
        for event in events:
            await self._insert_event(event)

    def get_datetime_with_timezone(self, tzinfo: datetime.timezone | None = None) -> datetime.datetime:
        if tzinfo is None:
            tzinfo = self.cached_tzinfo

        return datetime.datetime.now(tzinfo)

    async def fetch_events(self, page: int = 1, page_size: int = 80) -> list:
        print("Requesting")
        async with self.bot.session.get(
            'https://old.online.ntnu.no/api/v1/event/events/',
            params={
                'format': 'json',
                'page': 1,
                'page_size': page_size,
                'ordering': '-event_start'
            },
        ) as response:
            data = await response.json()

        results = data['results']
        if results:
            start_date = datetime.datetime.fromisoformat(results[-1]['start_date'])
            if self.cached_tzinfo is None:
                self.cached_tzinfo = start_date.tzinfo

            if start_date > self.get_datetime_with_timezone(tzinfo=start_date.tzinfo):
                additional = await self.fetch_events(page=page + 1)
                results.extend(additional)
            else:
                def check(result):
                    start_date = datetime.datetime.fromisoformat(result['start_date'])
                    return start_date > self.get_datetime_with_timezone(tzinfo=start_date.tzinfo)

                results = [r for r in results if check(r)]

        return results

    @commands.hybrid_command()
    async def test(self, ctx):
        print("Test")
        await ctx.send("Test")

        try:
            events = await self.fetch_events(page_size=80)
            print(events[-1]['title'])
            await ctx.send(f'Found {len(events)} events.')
        except:
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(NotifierCog(bot))
