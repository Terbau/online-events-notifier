from contextlib import redirect_stdout
from io import StringIO
import os
import textwrap
import time
import traceback
from typing import Optional
import discord
from discord.ext import commands


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.is_owner()
    @commands.hybrid_command(name='eval', aliases=['ev'])
    async def _eval(self, ctx, *, data: str):
        if data.startswith('```'):
            data = data.partition('\n')[2]
        data = data.strip('` \n')
        code = 'async def func():\n{}'.format(textwrap.indent(data, '    '))
        env = {
            'bot': self.bot,
            'ctx': ctx,
            'discord': discord,
            'commands': commands
        }
        try:
            exec(code, env)
        except Exception as e:
            return await ctx.send('```py\n{}\n```'.format(e))
        stdout = StringIO()
        func = env['func']
        try:
            with redirect_stdout(stdout):
                await func()
        except Exception:
            add_text = '\n{}'.format(traceback.format_exc())
        else:
            add_text = ''
        finally:
            value = stdout.getvalue()
            if value or add_text:
                if add_text == '':
                    await ctx.send_formatted(
                        f'```\n{value}{add_text}\n```',
                        title='Output'
                    )
                else:
                    await ctx.send_error(
                        f'```\n{value}{add_text}\n```',
                        header='Exception'
                    )

    @commands.is_owner()
    @commands.hybrid_command()
    async def cogs(self, ctx):
        files = []
        path = os.path.dirname(os.path.abspath(__file__))
        for file in os.listdir(path):
            if os.path.isfile(os.path.join(path, file)):
                if file.strip('.py') in self.bot.cogs:
                    files.append(True, file)
                else:
                    files.append(False, file)

        parts = []
        _sorted = sorted(files, key=lambda l: l[0], reverse=True)
        for loaded, file in _sorted:
            if loaded:
                parts.append('- [:white_check_mark:] **{}**'.format(file))
            else:
                parts.append('- [:x:] **{}**'.format(file))

        await ctx.send_formatted('\n'.join(parts))

    @commands.is_owner()
    @commands.hybrid_command()
    async def load(self, ctx, *, module):
        try:
            self.bot.load_extension(module)
        except commands.ExtensionError as e:
            await ctx.send_error(f'{e.__class__.__name__}: {e}')
        else:
            if ctx.channel.permissions_for(ctx.me).add_reactions:
                await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')
            else:
                await ctx.send_success('Loaded successfully.')

    @commands.is_owner()
    @commands.hybrid_command()
    async def unload(self, ctx, *, module):
        try:
            self.bot.unload_extension(module)
        except commands.ExtensionError as e:
            await ctx.send_error(f'{e.__class__.__name__}: {e}')
        else:
            if ctx.channel.permissions_for(ctx.me).add_reactions:
                await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')
            else:
                await ctx.send_success('Unloaded successfully.')

    @commands.is_owner()
    @commands.hybrid_command(name='reload', aliases=['r', 'rl'])
    async def _reload(self, ctx, *, module: str):
        content = module.lower()

        if not content.startswith('cogs.'):
            module = 'cogs.' + content

        cog = self.bot.get_cog(module)
        if cog is not None:
            method = getattr(cog, 'cog_reload', None)
            if method is not None:
                await method()

        try:
            try:
                await self.bot.reload_extension(module)
            except commands.errors.ExtensionNotLoaded:
                await self.bot.load_extension(module)

            await ctx.send_success(
                f'Extension {module} was successfully reloaded.',
                header='Success!'
            )

        except commands.ExtensionNotFound:
            return await ctx.send_error(
                f'No cog named {module}.',
                header=True
            )

        except Exception:
            print(f'Failed to reload {module}:\n{traceback.format_exc()}')
            await ctx.send_error(
                'An error occured while reloading this cog.',
                header=True
            )

    @commands.is_owner()
    @commands.hybrid_group(aliases=['db'])
    async def database(self, ctx):
        pass

    @commands.is_owner()
    @database.command()
    async def showtable(self, ctx, table, *, where_clauses=''):
        async with ctx.acquire():
            if where_clauses:
                cl = where_clauses.split()
                clause = ' WHERE ' + ' AND '.join(cl)
            else:
                clause = ''

            query = f'SELECT * FROM {table}{clause};'
            res = await ctx.db.fetch(query)
            await ctx.send_as_table_display(res)

    @commands.is_owner()
    @database.command()
    async def showtablefile(self, ctx, table, *, where_clauses=''):
        async with ctx.acquire():
            if where_clauses:
                cl = where_clauses.split()
                clause = ' WHERE ' + ' AND '.join(cl)
            else:
                clause = ''

            query = f'SELECT * FROM {table}{clause};'
            res = await ctx.db.fetch(query)
            display = ctx.get_as_table_display(res)
            await ctx.send_as_txt_file(display)

    @commands.is_owner()
    @database.command()
    async def fetch(self, ctx, *, query):
        async with ctx.acquire():
            res = await ctx.db.fetch(query)
            await ctx.send_as_table_display(res)

    @commands.is_owner()
    @database.command()
    async def fetchrow(self, ctx, *, query):
        async with ctx.acquire():
            res = await ctx.db.fetchrow(query)
            await ctx.send_as_table_display(res)

    @commands.is_owner()
    @database.command()
    async def filefetch(self, ctx, *, query):
        async with ctx.acquire():
            res = await ctx.db.fetch(query)
            display = ctx.get_as_table_display(res)
            await ctx.send_as_txt_file(display)

    @commands.is_owner()
    @database.command()
    async def filefetchrow(self, ctx, *, query):
        async with ctx.acquire():
            res = await ctx.db.fetchrow(query)
            display = ctx.get_as_table_display(res)
            await ctx.send_as_txt_file(display)

    @commands.is_owner()
    @database.command()
    async def execute(self, ctx, *, query):
        t = time.time()

        query = query.strip('`')
        if query.startswith('sql'):
            query = query[3:]

        try:
            async with ctx.acquire():
                res = await ctx.db.execute(query)
        except Exception as e:
            await ctx.send_error(f'```\n{type(e).__qualname__}\n{e}```')
        else:
            comp = time.time() - t
            await ctx.send_success(
                f'Successfully executed statement in {comp:.3f}s\n```\n{res}```'
            )

    @commands.hybrid_group(invoke_without_command=True)
    @commands.is_owner()
    @commands.guild_only()
    async def sync(self, ctx, guild_id: Optional[int], copy: bool = False) -> None:
        """Syncs the slash commands with the given guild"""

        if guild_id:
            guild = discord.Object(id=guild_id)
        else:
            guild = ctx.guild

        if copy:
            self.bot.tree.copy_global_to(guild=guild)

        commands = await self.bot.tree.sync(guild=guild)
        await ctx.send(f'Successfully synced {len(commands)} commands')

    @sync.command(name='global')
    @commands.is_owner()
    async def sync_global(self, ctx):
        """Syncs the commands globally"""

        commands = await self.bot.tree.sync(guild=None)
        await ctx.send(f'Successfully synced {len(commands)} commands')


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
