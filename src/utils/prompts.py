import discord
import asyncio


class Prompt:
    def __init__(self, bot, author_id, channel, *,
                 color=None,
                 timeout=2*60,
                 delete_after=True):
        self.bot = bot
        self.author_id = author_id
        self.channel = channel
        self.color = color or bot.config.get('colors', 'prompt')
        self.timeout = timeout
        self.delete_after = delete_after

        self.to_delete = []

    async def _delete(self):
        for m in self.to_delete:
            if m.author.id != self.bot.user.id:
                if self.delete_after and self.channel.guild is not None:
                    if not m.channel.permissions_for(self.me).manage_messages:
                        raise RuntimeError('Bot does not have Manage Messages '
                                           'permission.')

        await self.channel.delete_messages(self.to_delete)

    async def delete_messages(self):
        for m in self.to_delete:
            if m.author.id != self.bot.user.id:
                if self.delete_after and self.channel.guild is not None:
                    if not m.channel.permissions_for(self.me).manage_messages:
                        raise RuntimeError('Bot does not have Manage Messages '
                                           'permission.')

        if isinstance(self.delete_after, (int, float)):
            await asyncio.sleep(self.delete_after)

        await self._delete()

    async def prompt(self):
        raise NotImplementedError()

    async def run(self, *args, **kwargs):
        try:
            return self.prompt(*args, **kwargs)
        finally:
            self.bot.loop.create_task(self.delete_messages())


class YesOrNoPrompt:
    async def prompt(self, message):
        if not self.channel.permissions_for(self.me).add_reactions:
            raise RuntimeError('Bot does not have Add Reactions permission.')

        fmt = f'{message}\n\nReact with \N{WHITE HEAVY CHECK MARK} ' \
              f'to confirm or \N{CROSS MARK} to deny.'
        embed = discord.Embed(
            description=fmt,
            color=self.color
        )

        author_id = self.author_id
        msg = await self.channel(embed=embed)
        self.to_delete.append(msg)

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

        try:
            await self.bot.wait_for(
                'raw_reaction_add',
                check=check,
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            confirm = None

        return confirm


class PasswordPrompt(Prompt):
    async def prompt(self, password):
        if self.delete_after and self.channel.guild is not None:
            if not self.channel.permissions_for(self.me).manage_messages:
                raise RuntimeError('Bot does not have Manage Messages '
                                   'permission.')

        fmt = 'Please enter the password below to authenticate this action.'
        embed = discord.Embed(
            description=fmt,
            color=self.color
        )
        base = await self.channel.send(embed)
        self.to_delete.append(base)

        def check(m):
            if m.author.id != self.author_id:
                return False
            if self.channel.id != m.channel.id:
                return False

        try:
            message = await self.bot.wait_for(
                'message',
                check=check,
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                description='Sorry, you took too long. Action cancelled.',
                color=self.bot.config.get('colors', 'error')
            )
            m = await self.channel.send(embed=embed)
            self.to_delete.append(m)
            return False
        else:
            self.to_delete.append(message)

        if message.content != password:
            embed = discord.Embed(
                description='Incorrect password. Action cancelled.',
                color=self.bot.config.get('colors', 'error')
            )
            m = await self.channel.send(embed=embed)
            self.to_delete.append(m)
            return False

        return True
