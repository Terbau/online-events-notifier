import asyncio
import discord
import traceback

from collections import defaultdict
from utils import utils


class EmbedPaginator:
    def __init__(self, ctx, *,
                 author_only=True,
                 delete_after=True,
                 timeout=2 * 60,
                 enumerate_pages=True,
                 remove_reactions=True,
                 enable_unreactions=False):
        self.bot = ctx.bot
        self.ctx = ctx
        self.author = ctx.author

        self.author_only = author_only
        self.delete_after = delete_after
        self.timeout = timeout
        self.enumerate_pages = enumerate_pages
        self.remove_reactions = remove_reactions
        self.enable_unreactions = enable_unreactions

        self.current = 0
        self.pages = []
        self.task = None
        self.base = None
        self.base_other = None
        self.task_other = None
        self._inactive_event = asyncio.Event()
        self._closed = False

        self.actions = defaultdict(list)
        self.listeners = defaultdict(list)

        self.emojies = {
            '\U000025c0': 'left',
            '\U000025b6': 'right',
            '\U000026d4': 'stop',
        }
        self.named = {v: k for k, v in self.emojies.items()}

        self._emojies = [e for e in self.emojies]

    @property
    def current_page(self):
        return self.pages[self.current]

    async def wait_for_inactive(self):
        return await self._inactive_event.wait()

    def add_page(self, page):
        if not asyncio.iscoroutinefunction(getattr(page, 'construct_page', None)):
            raise TypeError('Pages must have an async construct_page method.')

        self.pages.append(page)

    def remove_page(self, page):
        self.pages = [p for p in self.pages if p != page]

    def add_action(self, emoji, coro, index=None):
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError('coro must be a coroutine.')

        if str(emoji) in self.emojies:
            raise ValueError('You cant register an action to this emoji.')

        self.actions[str(emoji)].append(coro)

        if index is not None:
            self._emojies.insert(index, str(emoji))
        else:
            self._emojies.append(str(emoji))

    def remove_reaction(self, emoji, coro):
        self.actions[str(emoji)] = [c for c in self.actions[str(emoji)] if c != coro]

    def add_listener(self, event, coro):
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError('coro must be a coroutine.')

        self.listeners[event].append(coro)

    def remove_listener(self, event, coro):
        self.listeners[event] = [c for c in self.listeners[event] if c != coro]

    async def dispatch_and_wait(self, event, *args, **kwargs):
        coros = self.listeners.get(event)
        if coros:
            await asyncio.gather(*[c(*args, **kwargs) for c in coros])

    def dispatch(self, event, *args, **kwargs):
        for coro in self.listeners.get(event, []):
            self.bot.loop.create_task(coro(*args, **kwargs))

    async def _load_page(self, embed):
        if self.enumerate_pages:
            numeration = f'Page {self.current+1}/{len(self.pages)}'
            text = embed.footer.text
            if text:
                embed.set_footer(text=f'{numeration} | {text}')
            else:
                embed.set_footer(text=numeration)

        await self.base.edit(embed=embed)

    async def construct(self, page):
        return await page.construct_embed()

    async def new_page(self):
        embed = await self.construct(self.current_page)
        await self._load_page(embed)

    async def reload_page(self):
        current_embed = self.base.embeds[0]
        embed = await self.construct(self.current_page)

        if not utils.cmp_embeds(current_embed, embed):
            await self._load_page(embed)

    async def _run(self):
        embed = await self.construct(self.current_page)
        self.base = await self.ctx.send(embed=embed)

        async def adder():
            for emoji in self._emojies:
                await self.base.add_reaction(emoji)

        self.bot.loop.create_task(adder())

        def check(payload):
            if self._closed:
                return False
            if payload.user_id == self.bot.user.id:
                return False
            elif self.author_only and payload.user_id != self.author.id:
                return False
            elif payload.message_id != self.base.id:
                return False
            elif str(payload.emoji) not in self._emojies:
                return False
            return True

        while True:
            async def waiter(event):
                return await self.bot.wait_for(event, check=check)

            tasks = [asyncio.create_task(waiter('raw_reaction_add'))]
            if self.enable_unreactions:
                tasks.append(asyncio.create_task(waiter('raw_reaction_remove')))

            done, pending = await asyncio.wait(
                tasks,
                timeout=self.timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Done is empty if wait timed out
            if not done:
                return await self.cleanup()

            # Cancel pending tasks (if any)
            for task in pending:
                task.cancel()

            payload = None
            for task in done:
                payload = task.result()

            str_emoji = str(payload.emoji)
            action = self.emojies.get(str_emoji)
            if action == 'left':
                if self.current == 0:
                    self.current = len(self.pages) - 1
                else:
                    self.current -= 1

                await self.new_page()
                self.dispatch('page_backwards')

            elif action == 'right':
                if self.current == len(self.pages) - 1:
                    self.current = 0
                else:
                    self.current += 1

                await self.new_page()
                self.dispatch('page_forward')

            elif action == 'stop':
                return await self.cleanup()

            else:
                coros = self.actions.get(str_emoji)
                if coros:
                    await asyncio.gather(*[c(payload) for c in coros])

            if self.remove_reactions:
                user = self.bot.get_user(payload.user_id)
                if user is None:
                    try:
                        user = await self.bot.fetch_user(payload.user_id)
                    except discord.DiscordException:
                        pass

                if user is not None and self.base is not None:
                    try:
                        await self.base.remove_reaction(payload.emoji, user)
                    except discord.Forbidden:
                        pass

    def run(self):
        self.task = utils.create_tracebacked_task(self._run())

    async def run_and_await(self):
        self.run()
        await self.wait_for_inactive()

    async def cleanup(self, allow_delete_after=True):
        if self._closed:
            return

        self._closed = True

        if allow_delete_after and self.delete_after:
            if self.base:
                try:
                    await self.base.delete()
                    self.base = None
                except discord.DiscordException:
                    pass

            try:
                await self.ctx.message.delete()
            except discord.DiscordException:
                pass

        try:
            await self.dispatch_and_wait('close')
        except Exception:
            traceback.print_exc()

        if self.task is not None and not self.task.cancelled():
            self.task.cancel()

        self._inactive_event.set()


class EmbedFieldPaginator:
    pass
