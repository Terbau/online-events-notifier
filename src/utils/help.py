import discord
import inspect
import sys
import traceback

from discord.ext import commands
from collections import OrderedDict

from discord.ext.commands.errors import CommandError


class NoAccess(commands.CommandError):
    pass


class NewHelpCommand(commands.HelpCommand):
    async def send_error_message(self, error):
        embed = discord.Embed(
            description=error,
            color=self.context.bot.error_color,
        )
        await self.get_destination().send(embed=embed)

    async def on_help_command_error(self, ctx, error):
        if isinstance(error, NoAccess):
            return await self.send_error_message(str(error))

        print(
            'Ignoring exception in help {}:'.format(ctx.command),
            file=sys.stderr
        )
        traceback.print_exception(
            type(error),
            error,
            error.__traceback__,
            file=sys.stderr
        )

    def get_command_signature(self, command):
        return '%s%s %s' % (self.context.clean_prefix, command.qualified_name, command.signature)

    def get_category(self, command, no_category='No Category'):
        cog = command.cog if isinstance(command, commands.Command) else command
        return cog.qualified_name if cog is not None else no_category

    async def filter_commands(self, commands, *, sort=False, key=None):
        """Same as https://github.com/Rapptz/discord.py/blob/a3f700c11f72202f6a7710ce07c7144a8b8c947d/discord/ext/commands/help.py#L546-L567
        except that it might now also return False if any commands were
        found but all checks failed. This is useful if you need to check
        if a user was denied access to all commands.
        """
        if sort and key is None:
            key = lambda c: c.name  # noqa: E731

        iterator = commands if self.show_hidden else filter(lambda c: not c.hidden, commands)
        if self.verify_checks is False or (self.verify_checks is None and not self.context.guild):
            return sorted(iterator, key=key) if sort else list(iterator)

        async def predicate(cmd):
            try:
                return await cmd.can_run(self.context)
            except CommandError:
                return False

        ret = []
        was_empty = True
        for cmd in iterator:
            was_empty = False
            valid = await predicate(cmd)
            if valid:
                ret.append(cmd)

        if not was_empty and not ret:
            return False

        if sort:
            ret.sort(key=key)

        return ret

    async def send_bot_help(self, mapping):
        prefix = self.context.clean_prefix  # TODO: Maybe drop prefix

        embed = discord.Embed(
            title='Help',
            color=0xf00ff0,
        )

        filtered = await self.filter_commands(c for cmds in mapping.values() for c in cmds)
        if filtered is not False:
            new_mapping = OrderedDict()
            for command in filtered:
                cog_name = self.get_category(command)
                try:
                    new_mapping[cog_name].append(command)
                except KeyError:
                    new_mapping[cog_name] = [command]

            for cog_name, cmds in new_mapping.items():
                if not cmds:
                    continue

                value = ', '.join(f'`{prefix}{c.name}`' for c in cmds)
                embed.add_field(
                    name=f'{cog_name} ({len(cmds)})',
                    value=value,
                    inline=False,
                )

        extra = f'\n\nUse `{prefix}help [command]` for more info about a command.\n' \
                f'Use `{prefix}help [category]` for more info about a category.'

        if not embed.fields:
            embed.description += f'\n\nNo commands was found :({extra}'
        else:
            embed._fields[-1]['value'] += extra

        await self.get_destination().send(embed=embed)

    async def send_cog_help(self, cog: commands.Cog):
        prefix = self.context.clean_prefix  # TODO: Maybe drop prefix
        filtered = await self.filter_commands(cog.get_commands())
        if filtered is False:
            raise NoAccess('You have no access to view this category.')

        parts = []
        for command in filtered:
            brief = command.brief or 'Description not found.'
            parts.append(f'`{self.get_command_signature(command)}` - {brief}')

        fmt = '`<arg>` means the argument is required\n' \
              '`[arg]` means it is optional\n\n' \
              '**Commands**\n'
        if parts:
            fmt += '\n'.join(parts)
        else:
            fmt += 'No commands found :('
        fmt += f'\n\nUse `{prefix}help [command]` for more info about a command.'

        embed = discord.Embed(
            title=f'Help | {self.get_category(cog)}',
            description=fmt,
            color=0xf00ff0,
        )
        await self.get_destination().send(embed=embed)

    def has_content(self, coro):
        iterator = (lx.strip() for lx in reversed(inspect.getsource(coro).splitlines()))
        for i, line in enumerate(iterator):
            if '#' in line:
                line = line.split('#')[0].strip()

            if line == '':
                continue

            if line.startswith('print(') or line.startswith('log.') or line.startswith('logger.'):
                continue

            if i == 0:
                if line not in ('pass', 'return'):
                    return True
            else:
                if line.startswith('async def'):
                    return False
                else:
                    return True

    async def send_command_help(self, command: commands.Command, is_group=False):
        try:
            ret = await command.can_run(self.context)
        except CommandError:
            ret = False

        if not ret:
            raise NoAccess('You have no access to view this command.')

        has_content = self.has_content(command.callback) if is_group else True
        parts = []

        description = command.description if command.description else 'No description found.'
        parts.append(f'**Description**\n{description}')

        if has_content:
            parts.append(
                '`<arg>` means the argument is required\n'
                '`[arg]` means it is optional\n\n'
                f'**Usage**\n`{self.get_command_signature(command).strip()}`'
            )

        if command.aliases:
            fmt_aliases = ', '.join(f'`{a}`' for a in command.aliases)
            parts.append(f'**Aliases**\n{fmt_aliases}')

        if is_group:
            filtered = await self.filter_commands(command.commands)
            if filtered is False and not has_content:
                raise NoAccess('You have no access to view this command.')

            if filtered:
                fmt_commands = ', '.join(f'`{c.name}`' for c in filtered)
                parts.append(
                    f'**Sub Commands**\n{fmt_commands}\n\n'
                    f'`{self.context.clean_prefix}{command.qualified_name} <sub command>`'
                )

        if command.help is not None:
            parts.append(f'**Help**\n{command.help}')

        if command.parent is not None:
            parts.append(f'This command is a subcommand of `{command.full_parent_name}`')

        embed = discord.Embed(
            title=f'Help | {command.name}',
            description='\n\n'.join(parts),
            color=0xf00ff0,
        )
        await self.get_destination().send(embed=embed)

    async def send_group_help(self, group):
        await self.send_command_help(group, is_group=True)
