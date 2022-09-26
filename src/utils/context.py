import asyncio
from typing import Optional, Union
import discord
import io

from discord.ext import commands as d_commands

from utils import utils


class _ContextDBAcquire:
    __slots__ = ('ctx', 'timeout')

    def __init__(self, ctx, timeout):
        self.ctx = ctx
        self.timeout = timeout

    def __await__(self):
        return self.ctx._acquire(self.timeout).__await__()

    async def __aenter__(self):
        await self.ctx._acquire(self.timeout)
        return self.ctx.db

    async def __aexit__(self, *args):
        await self.ctx.release()


class DiscordContext(d_commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pool = self.bot.pool
        self._db = None

    @property
    def discord_bot(self):
        return self.bot

    def __repr__(self):
        return '<Context>'

    async def _delete_silently(self, bases):
        try:
            await self.channel.delete_messages(bases)
        except discord.DiscordException:
            pass

    def _get_awaitable(self, future_or_event):
        if isinstance(future_or_event, asyncio.Future):
            return future_or_event

        return future_or_event.wait()

    async def _handle_delete(self,
                             bases,
                             *,
                             delete_after=None,
                             delete_when=None):
        if delete_after is not None and delete_when is None:
            await asyncio.sleep(delete_after)
            await self._delete_silently(bases)
        elif delete_after is None and delete_when is not None:
            await self._get_awaitable(delete_when)
            await self._delete_silently(bases)
        else:
            try:
                await asyncio.wait_for(self._get_awaitable(delete_when), timeout=delete_after)
            except asyncio.TimeoutError:
                pass

            await self._delete_silently(bases)

    async def send(self, *args,
                   delete_both_after=None,
                   delete_when: Optional[Union[asyncio.Event, asyncio.Future]] = None,
                   **kwargs):
        delete_after = kwargs.pop('delete_after', None)
        base = await super().send(*args, **kwargs)

        bases_to_delete = []
        if delete_both_after:
            bases_to_delete = (base, self.message)
        elif delete_after:
            bases_to_delete.append(base)

        if bases_to_delete:
            self.bot.loop.create_task(self._handle_delete(
                bases_to_delete,
                delete_after=delete_both_after or delete_after,
                delete_when=delete_when,
            ))

        return base

    async def send_as_table_display(self, entries, **kwargs):
        display = utils.get_as_table_display(entries, max_chars=1990)
        if len(display) > 2000:
            display = utils.get_as_table_display(entries)
            return await self.send_as_txt_file(display, **kwargs)
        return await self.send(f'```\n{display}```', **kwargs)

    async def prompt(self, message, *,
                     timeout=60.0,
                     delete_after=True,
                     reacquire=True,
                     author_id=None):
        """
        Returns
        --------
        Optional[bool]
            ``True`` if explicit confirm,
            ``False`` if explicit deny,
            ``None`` if deny due to timeout
        """

        if not self.channel.permissions_for(self.me).add_reactions:
            raise RuntimeError('Bot does not have Add Reactions permission.')

        embed = discord.Embed(
            description=(f'{message}\n\nReact with \N{WHITE HEAVY CHECK MARK} '
                         f'to confirm or \N{CROSS MARK} to deny.'),
            color=self.bot.color
        )

        author_id = author_id or self.author.id
        msg = await self.send(embed=embed)

        confirm = None

        def check(payload):
            nonlocal confirm

            if payload.message_id != msg.id or payload.user_id != author_id:
                return False

            codepoint = str(payload.emoji)

            if codepoint == '\N{WHITE HEAVY CHECK MARK}':
                confirm = True
                return True
            elif codepoint == '\N{CROSS MARK}':
                confirm = False
                return True

            return False

        for emoji in ('\N{WHITE HEAVY CHECK MARK}', '\N{CROSS MARK}'):
            await msg.add_reaction(emoji)

        if reacquire:
            await self.release()

        try:
            await self.bot.wait_for(
                'raw_reaction_add',
                check=check,
                timeout=timeout
            )
        except asyncio.TimeoutError:
            confirm = None

        try:
            if reacquire:
                await self.acquire()

            if delete_after:
                await msg.delete()
        finally:
            return confirm

    def tick(self, opt, label=None):
        lookup = {
            True: '<:greenTick:330090705336664065>',
            False: '<:redTick:330090723011592193>',
            None: '<:greyTick:563231201280917524>',
        }
        emoji = lookup.get(opt, '<:redTick:330090723011592193>')
        if label is not None:
            return f'{emoji}: {label}'
        return emoji

    @property
    def db(self):
        return self._db if self._db else self.pool

    async def _acquire(self, timeout):
        if self._db is None:
            self._db = await self.pool.acquire(timeout=timeout)
        return self._db

    def acquire(self, *, timeout=None):
        return _ContextDBAcquire(self, timeout)

    async def release(self):
        if self._db is not None:
            await self.bot.pool.release(self._db)
            self._db = None

    async def safe_send(self, content, *, escape_mentions=True, **kwargs):
        if escape_mentions:
            content = discord.utils.escape_mentions(content)

        if len(content) > 2000:
            fp = io.BytesIO(content.encode())
            kwargs.pop('file', None)
            return await self.send(
                file=discord.File(fp, filename='message_too_long.txt'),
                **kwargs
            )
        else:
            return await self.send(content, **kwargs)

    async def send_as_txt_file(self, content, **kwargs):
        fp = io.BytesIO(content.encode())
        kwargs.pop('file', None)
        return await self.send(
            file=discord.File(fp, filename='message.txt'),
            **kwargs
        )

    async def send_formatted(self, message,
                             header=None,
                             title=None,
                             color=None,
                             footer=None,
                             **kwargs):
        if color is None:
            color = self.bot.color

        embed = discord.Embed(title=title, color=color, description=message)

        if header is not None:
            embed.set_author(
                name=header,
                icon_url=(self.channel.author.avatar
                          if isinstance(self.channel, d_commands.Context)
                          else None)
            )

        if footer is not None:
            embed.set_footer(text=footer)

        return await self.send(embed=embed, **kwargs)

    async def send_success(self, message,
                           header=None,
                           color=None,
                           footer=None,
                           **kwargs):
        if color is None:
            color = self.bot.success_color

        embed = discord.Embed(color=color, description=message)

        if header is not None:
            embed.set_author(
                name=header or "Success",
                icon_url=("https://images-na.ssl-images-amazon.com/images/I/"
                          "71KUQgscjDL._SX425_.jpg")
            )

        if footer is not None:
            embed.set_footer(text=footer)

        return await self.send(embed=embed, **kwargs)

    async def send_error(self, message,
                         color=None,
                         footer=None,
                         header=True,
                         **kwargs):
        if color is None:
            color = self.bot.error_color

        embed = discord.Embed(color=color, description=message)

        if footer is not None:
            embed.set_footer(text=footer)

        if header:
            if isinstance(header, str):
                text = header
            else:
                text = "Error"

            embed.set_author(
                name=text,
                icon_url=("https://cdn.icon-icons.com/icons2/1380/PNG/512/"
                          "vcsconflicting_93497.png")
            )

        return await self.send(embed=embed, **kwargs)
