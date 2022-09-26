import asyncpg
import json
import discord
import asyncio

from enum import Enum
from discord.ext import commands
from typing import Any, List, Tuple
from . import db, paginator, utils


class ConfigError(Exception):
    pass


class ParseError(ConfigError):
    pass


class CircularDependency(ConfigError):
    pass


class MaxConcurrency(ConfigError):
    pass


class InvalidValue:
    def __init__(self, value: Any):
        self.value = value


class NullValue:
    def __bool__(self):
        return False


class MockContext:
    def __init__(self, bot, guild):
        self.bot = bot
        self.guild = guild

# Add required fields
    # Add empty fields that needs to be filled in
# Make sure string and raw content doesnt print anything that is too long
# Make some sort of backup stuff for formatting error

# Figure out how to store InvalidValue
# Make fields Nullable
# Add message to be sent explaining edit (get:_edit_formatting or whatever)

# how to dump invalid values
# make notset

# make it possible to depend on another field(s)

class ConfigField:
    """Base class of a config field.

    Parameters
    ----------
    key: :class:`str`
        The internal name of the field.
    name: :class:`str`
        The visible name of the field.
    default_value: Any
        The default value the field should use. If not specified, it will
        default to the subclass' default. If the subclass does not have a
        default value set and no value is passed, then an error will be raised.
    always_reload: :class:`bool`
        Whether or not the value should always dumped and re-loaded when
        safely fetched. Set this to true if the value could in theory become
        invalid after start. That could be someone deleting the channel, role or
        whatever is stored in the field. Defaults to ``True``. (Only useful if
        Config.use_cache is True)
    validate: Optional[Callable[[Any], :class:`bool`]]
        A callable which is used for custom validation of the field. If None
        is passed, then it defaults to the fields regular validation.
    on_edit: Callable[[:class:`discord.Guild`, Any], None]
        A callback which is called whenever an edit is successfully done.
    title: :class:`str`
        The title to use for the edit embed.
    description: :class:`str`
        The description to use for the edit embed.
    color: :class:`str`
        The color to use for the edit embed.
    """

    SQL_TYPE = None
    ANY_CONFIG_REQUIREMENT = []

    def __init__(self, key, name, *,
                 default_value=NullValue(),
                 always_reload=False,
                 validate=None,
                 on_edit=None,
                 description=None,
                 title='Config',
                 color=0x00ffff,
                 inactive_color=0x8b8d8f):
        self.key = key
        self.name = name

        attr = getattr(self, 'DEFAULT_VALUE', None)
        if attr is None and isinstance(default_value, NullValue):
            raise ValueError('A default value must be set for this field.')

        self.default_value = attr if isinstance(default_value, NullValue) else default_value
        self.always_reload = always_reload
        self._validate = validate
        self.on_edit = on_edit
        self.description = description
        self.title = title
        self.color = color
        self.inactive_color = inactive_color

        self.dependencies = []

    def _inject_bot(self, bot):
        self.bot = bot

    def add_dependency(self, field):
        for dep in field.walk_dependencies():
            if dep is self:
                raise CircularDependency(
                    f'Circular dependency detected between {self.name} and {dep.name}.'
                )

        self.dependencies.append(field)

    def remove_dependency(self, field):
        try:
            self.dependencies.remove(field)
        except ValueError:
            pass

    def walk_dependencies(self):
        for dependency in self.dependencies:
            yield dependency
            yield from dependency.walk_dependencies()

    def _path_builder_walker(self, list_: list):
        for dep in self.dependencies:
            if dep.dependencies:
                l_copy = list_.copy()
                l_copy.append(dep)
                yield from dep._path_builder_walker(l=l_copy)
            else:
                list_.append(dep)
                yield list_

    def is_active(self, data):
        for dep in self.walk_dependencies():
            try:
                value = data[dep.key]
            except KeyError:
                return False

            if not dep.validate(value):
                return False

        return True

    def walk_dependency_paths(self):
        for path in self._path_builder_walker(l=[self]):
            yield path

    async def do_parse(self, guild, inp):
        res = await self.parse(guild, inp)
        if self.on_edit is not None:
            self.on_edit(guild, res)

        return res

    def validate_setup(self):
        """Override if the field needs some kind of validation upon
        config creation."""
        return True

    def validate(self, value):
        if self._validate is not None:
            return self._validate(value)

        return self.default_validate(value)

    def default_validate(self, value):
        """Override if the field needs special validation to determine if
        the value is correct."""
        return not isinstance(value, InvalidValue)

    def dump(self, value):
        """Override if the fields needs some special dump functionality."""
        return value

    def load(self, guild, value):
        """Override if the field needs some special functionality when
        loaded from the config."""
        return value

    def get_formatted(self, value):
        """Override if the field needs some kind of special formatting
        for the embed page."""
        return value

    def get_formatted_edit(self):
        """Override if the field needs a special text for the edit message."""
        return 'Please enter the value to set.'

    async def parse(self, guild, inp):
        """Override if the field needs some kind of parsing from edit input."""
        return inp

    async def construct_page(self, paginator):
        value = paginator.data[self.key]
        color = self.color

        fmt = ''
        is_active = self.is_active(paginator.data)

        if self.description is not None:
            fmt += self.description + '\n\n'

        not_active_invalid = False
        if isinstance(value, InvalidValue):
            if value.value is None:
                value_fmt = 'N/A'
            else:
                value_fmt = value.value

            try:
                text = f'**Invalid(**`{self.get_formatted(value_fmt)}`**)**'
            except Exception:
                text = f'**Invalid**```\n{value_fmt}```'

            if is_active:
                fmt += f':warning: This field must be edited :warning:\n\n' \
                       f'Currently set:\n{text}'

                color = utils.get_color(
                    paginator.bot.config.get('colors', 'error')
                )
            else:
                not_active_invalid = True
                fmt += f'Currently set:\n{text}'
                color = 0xe3902b
        else:
            if not is_active:
                color = self.inactive_color

            text = self.get_formatted(value)
            fmt += f'Currently set:\n{text}'

        if self.dependencies:
            fmt += '\n\n'
            if not_active_invalid:
                fmt += 'This field must be edited when any dependency is enabled.\n'

            paths = ','.join(
                f"`{'/'.join(f.name for f in reversed(path[1:]))}`"
                for path in self.walk_dependency_paths()
            )
            fmt += f'_Depends on {paths}_'

        embed = discord.Embed(
            title=f'{self.title} | {self.name}',
            description=fmt,
            color=color,
        )
        embed.set_footer(text=f'Click {paginator.EDIT_EMOJI} to edit')
        return embed


class BoolField(ConfigField):
    SQL_TYPE = 'BOOL'

    def load(self, guild, value):
        if not isinstance(value, bool):
            return InvalidValue(value)

        return value

    def get_formatted(self, bool_):
        return f'**{bool_}**'

    def get_formatted_edit(self):
        return 'Please enter one of the two following values:```\nTrue\nFalse```'

    async def parse(self, guild, inp):
        if inp.lower() == 'true':
            return True
        elif inp.lower() == 'false':
            return False

        raise ParseError(f'{inp} is not a valid boolean.')


class StringField(ConfigField):
    SQL_TYPE = 'CHARACTER VARYING'

    def __init__(self, *args, min_size=0, max_size=100, **kwargs):
        super().__init__(*args, **kwargs)

        self.min_size = min_size
        self.max_size = max_size

    def load(self, guild, value):
        if not isinstance(value, str):
            return InvalidValue(value)

        return value

    def get_formatted(self, string):
        if string == '':
            string = 'None'
        string = string.replace("`", "\`")  # noqa: W605
        return f'`{string}`'

    def get_formatted_edit(self):
        return 'Please enter the value to set. Enter `clear`/`none` to clear the text.'

    async def parse(self, guild, inp):
        if inp.lower() in ('none', 'clear'):
            inp = ''
        elif inp.startswith('"') and inp.endswith('"'):
            inp = inp[1:-1]

        if len(inp) < self.min_size:
            raise ParseError(f'Length of content must exceed or equal {self.min_size} characters.')

        if len(inp) > self.max_size:
            raise ParseError(f'Length of content must not exceed {self.max_size} characters.')

        return inp


class StringsField(ConfigField):
    SQL_TYPE = 'JSON'
    DEFAULT_VALUE = []

    def __init__(self, *args, min_strings=0, max_strings=5, min_size=1, max_size=100, **kwargs):
        super().__init__(*args, **kwargs)

        self.min_strings = min_strings
        self.max_strings = max_strings
        self.min_size = min_size
        self.max_size = max_size

    def dump(self, value):
        return json.dumps(value)

    def load(self, guild, value):
        return json.loads(value)

    def get_formatted(self, value):
        values = '\n'.join(f'`{v}`' for v in (s.replace("`", "\`") for s in value))  # noqa: W605
        if not values:
            values = 'None set'

        return values

    def get_formatted_edit(self):
        return 'Please enter the values to set. Split each input with a new line.\n\n' \
               'Tip: If you need a trailing space on one of your values, you can achieve ' \
               'this by quoting the line.\n\nExample:```\nmyvalue\n"myprefix "\nanother one```\n' \
               'Enter `clear`/`none` to clear the inputs.'

    async def parse(self, guild, inp):
        lines = inp.splitlines()

        result = []
        for line in lines:
            if line.lower() in ('none', 'clear'):
                continue

            if line.startswith('"') and line.endswith('"'):
                line = line[1:-1]

            if len(line) < self.min_size:
                raise ParseError(f'Length of a line must exceed or equal {self.min_size} characters.')

            if len(line) > self.max_size:
                raise ParseError(f'Length of a line must not exceed {self.max_size} characters.')

            result.append(line)

        if len(result) < self.min_strings:
            raise ParseError(f'Amount of values must exceed or equal {self.min_strings}.')

        if len(result) > self.max_strings:
            raise ParseError(f'Amount of values must not exceed {self.max_strings}.')

        return result


class IntField(ConfigField):
    SQL_TYPE = 'INTEGER'

    def __init__(self, *args, min_size=1, max_size=100, **kwargs):
        super().__init__(*args, **kwargs)

        self.min_size = min_size
        self.max_size = max_size

    def load(self, guild, value):
        if not isinstance(value, int):
            return InvalidValue(value)

        return value

    def get_formatted(self, int_):
        return f'**{int_}**'

    def get_formatted_edit(self):
        return 'Please enter the number to set.'

    async def parse(self, guild, inp):
        try:
            val = int(inp)
        except ValueError:
            raise ParseError(f'{inp} is not a valid number.')

        if len(val) < self.min_size:
            raise ParseError(f'The number must exceed or equal {self.min_size}.')

        if len(val) > self.max_size:
            raise ParseError(f'The number must not exceed {self.max_size}.')

        return val


class RawContentField(ConfigField):
    SQL_TYPE = 'CHARACTER VARYING'

    def __init__(self, *args, min_size=0, max_size=1500, **kwargs):
        super().__init__(*args, **kwargs)

        self.min_size = min_size
        self.max_size = max_size

    def load(self, guild, value):
        if not isinstance(value, str):
            return InvalidValue(value)

        return value

    def get_formatted(self, content):
        content = content.replace('`', '\`')  # noqa: W605

        # This is just for better formatting since its super ugly
        # when you make a codeblock with no content on discord.
        if not content:
            content = 'None'

        return f'```\n{content}```'

    def get_formatted_edit(self):
        return 'Please enter the content to set. Enter `clear`/`none` to clear the content.'

    async def parse(self, guild, inp):
        if inp.lower() in ('none', 'clear'):
            inp = ''

        if len(inp) < self.min_size:
            raise ParseError(f'Length of the content must exceed or equal {self.min_size} characters.')

        if len(inp) > self.max_size:
            raise ParseError(f'Length of the content must not exceed {self.max_size} characters.')

        return inp


class ChannelField(ConfigField):
    SQL_TYPE = 'BIGINT'
    ANY_CONFIG_REQUIREMENT = ['GuildConfig']

    def dump(self, channel):
        if not channel:
            return channel
        return channel.id

    def load(self, guild, value):
        channel = guild.get_channel(value)
        if channel is None:
            return InvalidValue(value)

        return channel

    def get_formatted(self, channel):
        return channel.mention if isinstance(channel, discord.TextChannel) else channel

    def get_formatted_edit(self):
        return 'Please tag or enter the id/name of the channel to set.'

    async def parse(self, guild, inp):
        ctx = MockContext(self.bot, guild)
        try:
            return await commands.TextChannelConverter().convert(ctx, inp)
        except commands.CommandError:
            raise ParseError('The channel entered was not found.')


class RoleField(ConfigField):
    SQL_TYPE = 'BIGINT'
    ANY_CONFIG_REQUIREMENT = ['GuildConfig']

    def dump(self, role):
        if not role:
            return role
        return role.id

    def load(self, guild, value):
        role = guild.get_role(value)
        if role is None:
            return InvalidValue(role)

        return role

    def get_formatted(self, role):
        return role.mention if isinstance(role, discord.Role) else role

    def get_formatted_edit(self):
        return 'Please tag or enter the id/name of the role to set.'

    async def parse(self, guild, inp):
        ctx = MockContext(self.bot, guild)
        try:
            return await commands.RoleConverter().convert(ctx, inp)
        except commands.CommandError:
            raise ParseError('The role entered was not found.')


class RolesField(ConfigField):
    SQL_TYPE = 'JSON'
    DEFAULT_VALUE = []
    ANY_CONFIG_REQUIREMENT = ['GuildConfig']

    def __init__(self, *args, min_size=0, max_size=10, **kwargs):
        super().__init__(*args, **kwargs)

        self.min_size = min_size
        self.max_size = max_size

    def dump(self, roles):
        return json.dumps([r.id for r in roles])

    def load(self, guild, value):
        roles = [guild.get_role(v) for v in json.loads(value)]
        if None in roles:
            return InvalidValue(value)

        return roles

    def get_formatted(self, roles):
        roles = '\n'.join(r.mention for r in roles)
        if not roles:
            roles = 'None set'

        return roles

    def get_formatted_edit(self):
        return 'Please tag or enter the ids/names of the roles to set. Split the roles with a new line.\n' \
               'Example:```\n@role1\n@role2\n@role3```\nEnter `clear`/`none` to clear the roles.'

    async def parse(self, guild, inp):
        ctx = MockContext(self.bot, guild)

        lines = inp.splitlines()

        roles = []
        for identifier in lines:
            if identifier.lower() in ('none', 'clear'):
                continue

            try:
                role = await commands.RoleConverter().convert(ctx, identifier)
                roles.append(role)
            except commands.CommandError:
                raise ParseError(f'{identifier} was not found.')

        if len(roles) < self.min_size:
            raise ParseError(f'You must specify at least {self.min_size} roles.')

        if len(roles) > self.max_size:
            raise ParseError(f'You must not specify more than {self.max_size} roles.')

        return roles


# Only works with upper cased enum property names.
class EnumField(ConfigField):
    SQL_TYPE = 'CHARACTER VARYING'

    def dump(self, enum):
        return enum.name

    def set_enum(self, enum):
        if not isinstance(enum, Enum):
            raise TypeError('enum must be a enum.Enum object.')

        self.enum = enum

    def validate_setup(self):
        return hasattr(self, 'enum')

    def load(self, guild, value):
        return self.enum[value]

    def get_formatted(self, enum):
        return enum.name

    def get_formatted_edit(self):
        fields = '\n'.join(f'**{f.name}** - {f.value}' for f in self.enum)
        return f'Please enter one of the following values:\n{fields}'

    async def parse(self, guild, inp):
        try:
            return self.enum[inp.upper()]
        except KeyError:
            raise ParseError(f'{inp} is not valid.')


class PaginatedConfigEditor(paginator.EmbedPaginator):
    EDIT_EMOJI = '\U00002699'

    def __init__(self, ctx, cfg: 'BaseConfig', data, identifier=None):
        super().__init__(
            ctx,
            remove_reactions=False,
            enable_unreactions=True,
        )

        self.cfg = cfg
        self.data = data

        self.edit_base = None
        self.user_message = None
        self.edit_started_event = asyncio.Event()
        self.identifier = identifier or ctx.guild.id

        self.add_action(self.EDIT_EMOJI, self.edit_action, index=2)
        self.add_listener('page_forward', self.on_new_page)
        self.add_listener('page_backwards', self.on_new_page)
        self.add_listener('close', self.on_close)

    async def construct(self, page):
        return await page.construct_page(self)

    async def edit_action(self, payload):
        if self.edit_base is not None:
            await self.cleanup_edit()

        self.edit_started_event.set()

        page = self.current_page
        self.edit_base = await self.ctx.send_formatted(page.get_formatted_edit())

        def check(message):
            if message.channel.id != self.ctx.channel.id:
                return False
            elif message.author.id != payload.user_id:
                return False
            return True

        try:
            self.user_message = message = await self.bot.wait_for(
                'message',
                check=check,
                timeout=60
            )
        except asyncio.TimeoutError:
            return await self.cleanup_edit()

        try:
            value = await page.do_parse(self.ctx.guild, message.content)
        except ParseError as e:
            await self.cleanup_edit()
            return await self.ctx.send_error(
                f'Could not edit the field.\n\nError:```\n{e}```',
                delete_both_after=10,
                delete_when=self.edit_started_event,
            )

        if self.data[page.key] != value:
            await self.cfg.dump_and_update_config_field(
                self.identifier,
                page,
                value,
            )
            await self.reload_page()

        await self.cleanup_edit()

    async def cleanup_edit(self):
        self.edit_started_event.clear()

        messages = []
        if self.user_message is not None and self.ctx.guild is not None:
            messages.append(self.user_message)
            self.user_message = None

        if self.edit_base is not None:
            messages.append(self.edit_base)
            self.edit_base = None

        try:
            await self.ctx.channel.delete_messages(messages)
        except discord.HTTPException:
            pass

    async def on_new_page(self):
        await self.cleanup_edit()

    async def on_close(self):
        await self.cleanup_edit()

class BaseConfig:
    HAS_LOADED = False

    def __init__(self, bot, key, use_cache=True):
        self.bot = bot
        self.key = key  # Never let key be userinput!!
        # self.table_name = f'config_{key}'
        self.use_cache = use_cache

        self.fields = {}
        self._cache = {}
        self._editors = {}

        self._setup_lock = utils.LockEvent()
        self._is_setup = False

    @property
    def table_name(self):
        raise NotImplementedError

    def get_identifier_from_ctx(self, ctx):
        raise NotImplementedError

    def _load_field(self, identifier, field, data):
        raise NotImplementedError

    def _check_field_validity(self, class_name, field):
        if field.ANY_CONFIG_REQUIREMENT:
            if class_name not in field.ANY_CONFIG_REQUIREMENT:
                return TypeError("Cannot use this field in this config")

    async def _setup(self):
        async with self._setup_lock:
            if not self.fields:
                raise RuntimeError('At least one field must be added to the config.')

            await self._create_table_and_validate()
            self._is_setup = True

    def setup(self):
        self.bot.loop.create_task(self._setup())

    async def setup_and_wait(self):
        self.setup()
        await self._setup_lock.wait()

    def add_field(self, field):
        if not field.validate_setup():
            raise RuntimeError(f'Field {field.key} was not properly set up.')

        field._inject_bot(self.bot)

        self.fields[field.key] = field
        return field

    def remove_field(self, field):
        try:
            del self.fields[field.key]
        except KeyError:
            pass

    def get_field(self, key):
        return self.fields.get(key)

    def get_config(self, identifier):
        return self._cache.get(identifier)

    def _store_config(self, identifier, data):
        self._cache[identifier] = data

    def add_editor(self, identifier, editor):
        if identifier in self._editors:
            raise RuntimeError(f'An editor already exists for {identifier}')

        self._editors[identifier] = editor

    def remove_editor(self, identifier, allow_delete_after=False):
        try:
            editor = self._editors.pop(identifier)
        except KeyError:
            pass
        else:
            self.bot.loop.create_task(
                editor.cleanup(allow_delete_after=allow_delete_after)
            )

    async def validate_config(self, identifier, reload=True):
        data = await self.fetch_and_load_config(identifier)

        if reload:
            self.reload_data(identifier, data)

        for field in self.fields.values():
            if field.is_active(data):
                if not field.validate(data[field.key]):
                    return False

        return True

    async def run_paginator(self, ctx):
        await self._setup_lock.wait()
        if not self._is_setup:
            raise RuntimeError('Config is not setup yet by setup().')

        identifier = self.get_identifier_from_ctx(ctx)

        if identifier in self._editors:
            raise MaxConcurrency(f'A config editor already exists for {identifier}')

        data = await self.fetch_and_load_config(identifier)
        self.reload_data(identifier, data)
        paginator = PaginatedConfigEditor(ctx, self, data, identifier=identifier)
        for field in self.fields.values():
            paginator.add_page(field)

        async def close_callback():
            self.remove_editor(identifier)

        paginator.add_listener('close', close_callback)
        self.add_editor(identifier, paginator)
        await paginator.run_and_await()

    def reload_data(self, identifier, data):
        for field in self.fields.values():
            value = data[field.key]
            if self.use_cache and field.always_reload and not isinstance(value, InvalidValue):
                new_value = self._load_field(identifier, field, field.dump(value))
                data[field.key] = new_value

        return data

    async def _create_table(self, con=None):
        async with db.MaybeAcquire(con, self.bot.pool) as con:
            parts = (f'{f.key} {f.SQL_TYPE}' for f in self.fields.values())
            query = f'CREATE TABLE {self.table_name} (identifier BIGINT, {", ".join(parts)});'
            try:
                await con.execute(query)
            except asyncpg.DuplicateTableError:
                return False
            return True

    async def _validate_field(self, field, con=None):
        async with db.MaybeAcquire(con, self.bot.pool) as con:
            query = f'SELECT {field.key} FROM {self.table_name} WHERE 1 = 0;'
            try:
                await con.fetch(query)
            except asyncpg.UndefinedColumnError:
                return field

    async def _create_table_and_validate(self, con=None):
        async with db.MaybeAcquire(con, self.bot.pool) as con:
            res = await self._create_table(con=con)
            if res is True:
                return

        values = await asyncio.gather(
            *[self.bot.loop.create_task(self._validate_field(f))
                for f in self.fields.values()]
        )

        async with self.bot.pool.acquire() as con:
            fields = [f for f in values if f is not None]
            if fields:
                parts = ', '.join(f'{f.key} {f.SQL_TYPE}' for f in fields)
                query = f'ALTER TABLE {self.table_name} ADD {parts};'
                await con.execute(query)

                clauses = ', '.join(f'{f.key} = ${i}' for i, f in enumerate(fields, 1))
                query = f'UPDATE {self.table_name} SET {clauses};'
                await con.execute(
                    query,
                    *[f.dump(f.default_value) for f in fields]
                )

    def _load_data(self, identifier, data):
        data = dict(data)
        for field in self.fields.values():
            if field.key not in data:
                data[field.key] = self._load_field(identifier, field, field.dump(field.default_value))
            else:
                data[field.key] = self._load_field(identifier, field, data[field.key])

        return data

    def _dump_field(self, field, value):
        try:
            res = field.dump(value)
            if isinstance(res, InvalidValue):
                return None

            return res
        except Exception:
            return None

    async def create_row(self, identifier, con=None):
        dumped = {k: f.dump(f.default_value) for k, f in self.fields.items()}
        keys = ', '.join(dumped.keys())
        placeholders = ', '.join(f'${i}' for i in range(1, len(dumped) + 2))
        async with db.MaybeAcquire(con, self.bot.pool) as con:
            query = f'INSERT INTO {self.table_name} (identifier, {keys}) VALUES ({placeholders});'
            await con.execute(
                query,
                identifier,
                *list(dumped.values())
            )

        return dumped

    async def fetch_config(self, identifier, create_if_not_exists=True, con=None):
        await self._setup_lock.wait()
        if not self._is_setup:
            raise RuntimeError('Config is not setup yet by setup().')

        async with db.MaybeAcquire(con, self.bot.pool) as con:
            query = f'SELECT * FROM {self.table_name} WHERE identifier = $1;'
            res = await con.fetchrow(query, identifier)
            if res is None and create_if_not_exists:
                res = await self.create_row(identifier, con=con)
            elif res is None:
                return None

            return res

    async def fetch_and_load_config(self, identifier, cache=True, create_if_not_exists=True, con=None):
        if cache:
            data = self.get_config(identifier)
            if data is not None:
                return data

        res = await self.fetch_config(
            identifier,
            create_if_not_exists=create_if_not_exists,
            con=con,
        )
        if res is None:
            return None

        data = self._load_data(identifier, res)
        if self.use_cache:
            self._store_config(identifier, data)

        return data

    async def fetch_and_load_config_field(self, identifier, key, cache=True, con=None):
        data = None
        if cache:
            data = self.get_config(identifier)

        if data is None:
            data = await self.fetch_and_load_config(
                identifier,
                cache=cache,
                con=con,
            )

            if data is None:
                return None

        return data.get(key)

    def _get_iters(self, o):
        if isinstance(o, dict):
            key_iter = lambda: o.keys()  # noqa: E731
            value_iter = lambda: o.values()  # noqa: E731
        else:
            key_iter = lambda: (e[0] for e in o)  # noqa: E731
            value_iter = lambda: (e[1] for e in o)  # noqa: E731

        return key_iter, value_iter

    async def update_config_fields(self, identifier, data: List[Tuple[str, Any]], con=None):
        await self._setup_lock.wait()
        if not self._is_setup:
            raise RuntimeError('Config is not setup yet by setup()')

        key_iter, value_iter = self._get_iters(data)

        clauses = ', '.join(f'{k} = ${i}' for i, k in enumerate(key_iter(), 2))
        async with db.MaybeAcquire(con, self.bot.pool) as con:
            query = f'UPDATE {self.table_name} SET {clauses} WHERE identifier = $1;'
            await con.execute(
                query,
                identifier,
                *list(value_iter()),
            )

    async def update_config_field(self, identifier, key, value, con=None):
        await self.update_config_fields(identifier, (key, value), con=con)

    async def dump_and_update_config_fields(self, identifier, data: List[Tuple[ConfigField, Any]], con=None):
        if self.use_cache:
            g_data = self.get_config(identifier)
            if g_data is not None:
                for field, value in data:
                    g_data[field.key] = value

        key_iter, value_iter = self._get_iters(data)

        # Using a list comp instead of a generator since it needs to be iterated over multiple
        # times and I dont want dump() to be called each time.
        dumped = [(f.key, self._dump_field(f, v)) for f, v in zip(key_iter(), value_iter())]
        await self.update_config_fields(identifier, dumped, con=con)

    async def dump_and_update_config_field(self, identifier, field, value, con=None):
        await self.dump_and_update_config_fields(identifier, ((field, value),), con=con)

    async def safe_fetch_field(self, identifier, key, cache=True, con=None):
        field = self.get_field(key)
        if field is None:
            raise KeyError(f'No field exists by the key {key}.')

        value = await self.fetch_and_load_config_field(identifier, key, cache=True, con=None)
        if not self.use_cache or not field.always_reload or isinstance(value, InvalidValue):
            return value

        new_value = self._load_field(identifier, field, field.dump(value))
        data = self.get_config(identifier)
        if data is not None:
            data[key] = new_value

        return new_value


class GuildConfig(BaseConfig):
    @property
    def table_name(self):
        return f'config_guild_{self.key}'

    def get_identifier_from_ctx(self, ctx):
        return ctx.guild.id

    def _load_field(self, identifier, field, data):
        self._check_field_validity(self.__class__.__name__, field)

        guild = self.bot.get_guild(identifier)
        if guild is None:
            raise ConfigError(f"Couldn't find guild with id {identifier}")

        return field.load(guild, data)


class UserConfig(BaseConfig):
    @property
    def table_name(self):
        return f'config_user_{self.key}'

    def get_identifier_from_ctx(self, ctx):
        return ctx.author.id

    def _load_field(self, identifier, field, data):
        self._check_field_validity(self.__class__.__name__, field)
        return field.load(None, data)


class ConfigManager:
    def __init__(self, bot):
        self.bot = bot
        self._configs = {}

    def add_config(self, config, cog=None, allow_delete_after_on_unload=False):
        self._configs[config.key] = config

        def callback():
            self.remove_config(
                config,
                allow_delete_after=allow_delete_after_on_unload,
            )

        if cog is not None:
            cog._register_close_callback(callback)

    def remove_config(self, config, allow_delete_after=False):
        for editor in config._editors.copy().values():
            identifier = config.get_identifier_from_ctx(editor.ctx)

            config.remove_editor(
                identifier,
                allow_delete_after=allow_delete_after,
            )

        try:
            del self._configs[config.key]
        except KeyError:
            pass

    def get_config(self, key):
        return self._configs.get(key)
