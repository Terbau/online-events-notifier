import asyncio
import datetime
import logging
import os
import traceback
import asyncpg
import aiohttp
import discord

from logging.handlers import RotatingFileHandler
from discord.ext import commands
from dotenv import load_dotenv, find_dotenv
from utils.context import DiscordContext
from utils.config import ConfigManager, MaxConcurrency, GuildConfig, UserConfig, StringsField
from utils.help import NewHelpCommand
from utils.checks import guild_owner_or_permissions
from utils.utils import get_color_from_hex_string

load_dotenv(find_dotenv(), override=True)
logger = logging.getLogger(__name__)
DEFAULT_PREFIX = os.environ.get('DEFAULT_COMMAND_PREFIX', '!')
intents = discord.Intents.all()

cogs = (
    'admin',
    'notifier',
)


async def get_prefix(bot, message):
    if message.guild is None:
        prefixes = (DEFAULT_PREFIX,)
    else:
        prefixes = await bot.main_config.safe_fetch_field(
            message.guild.id,
            'prefixes',
        )

    return commands.when_mentioned_or(*prefixes)(bot, message)


@guild_owner_or_permissions(administrator=True)
@commands.hybrid_command(name='config', aliases=['setup'])
async def config_command(ctx):
    try:
        await ctx.bot.main_config.run_paginator(ctx)
    except MaxConcurrency:
        await ctx.send_error(
            'Someone else is already editing this servers config.'
        )


@commands.hybrid_command(name='owconfig', aliases=['userconfig'])
async def owconfig_command(ctx):
    await ctx.bot.ow_user_config.run_paginator(ctx)


class OWNotifierBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=get_prefix,
            description='A bot that notifies you when changes are made on Online Web (online.ntnu.no).',
            help_command=NewHelpCommand(),
            owner_id=os.environ.get('OWNER_ID'),
            intents=intents,
        )

        self.pool = None
        self.guild_config_manager = ConfigManager(self)
        self.user_config_manager = ConfigManager(self)

        self.color = get_color_from_hex_string(os.environ.get('COLOR', "0x99AAFF"))
        self.success_color = get_color_from_hex_string(os.environ.get('SUCCESS_COLOR', "0x00FF00"))
        self.error_color = get_color_from_hex_string(os.environ.get('ERROR_COLOR', "0xFF0000"))

        self.setup_logging()

    async def get_context(self, message, *, cls=None):
        return await super().get_context(message, cls=cls or DiscordContext)

    async def load_other(self):
        self.main_config = cfg = GuildConfig(self, 'main')
        cfg.add_field(StringsField(
            'prefixes',
            'Prefixes',
            default_value=[DEFAULT_PREFIX],
            min_size=1,
            max_size=30,
        ))
        cfg.setup()

        self.guild_config_manager.add_config(cfg)
        self.add_command(config_command)

        self.ow_user_config = cfg = UserConfig(self, 'ow_user')
        cfg.add_field(StringsField(
            'testfield',
            'TestField',
            default_value=["Test1", "Test2"],
            min_size=1,
            max_size=30,
        ))
        cfg.setup()

        self.user_config_manager.add_config(cfg)
        self.add_command(owconfig_command)

    async def setup_hook(self):
        try:
            await self.init_application()
        except Exception as e:
            logger.exception('Failed to initialize application.')
            await self.process_close()
            raise

    async def on_ready(self):
        print("--=--------------------------------=--")
        print("Connected with bot {} to:".format(self.user.name))
        print("==+== ID: {} ==+==".format(self.user.id))
        print("--=--------------------------------=--")

        if not hasattr(self, "uptime"):
            self.uptime = datetime.datetime.utcnow()

    def setup_logging(self):
        logger.info('Setting up logging.')

        self.log_handler = RotatingFileHandler(
            filename='./logs/bot.log',
            mode='w',
            maxBytes=10 * 1024 * 1014,
            backupCount=2,
            encoding='utf-8'
        )
        self.log_handler.setFormatter(
            logging.Formatter('%(asctime)s:%(levelname)s:%(name)s:'
                              ' %(message)s')
        )

        self.add_logger(logger)

    def add_logger(self, log, level=logging.DEBUG):
        if level:
            log.setLevel(level=level)
        log.addHandler(self.log_handler)
        logger.info(f'Added logger {log.name}.')

    async def setup_db(self):
        self.pool = await asyncpg.create_pool(
            host=os.environ['POSTGRES_HOST'],
            port=os.environ.get('POSTGRES_PORT', 5432),
            user=os.environ.get('POSTGRES_USER', 'postgres'),
            password=os.environ.get('POSTGRES_PASSWORD'),
            database=os.environ.get('POSTGRES_DATABASE', 'postgres'),
        )
        print("Database connection established.")

        statements = [
            (
                'CREATE TABLE IF NOT EXISTS ow_events ('
                'id INTEGER PRIMARY KEY,'
                'title TEXT,'
                'description TEXT,'
                'start_date TIMESTAMP,'
                'end_date TIMESTAMP,'
                'organizer INT,'
                'last_updated TIMESTAMP'
                ')'
            ),
        ]
        if statements:
            async with self.pool.acquire() as con:
                await con.execute('\n'.join(statements))
                logger.info('Created necessary database tables.')

    async def close_db(self):
        await self.pool.close()

    async def init_application(self):
        await self.setup_db()
        await self.load_other()
        await self.load_cogs()

        self.session = aiohttp.ClientSession()

    async def shutdown_application(self):
        tasks = [self.close_db()]

        if tasks:
            await asyncio.gather(*tasks)

    async def load_cogs(self):
        print("Loaded cogs:")
        for cog in cogs:
            try:
                await self.load_extension("cogs." + cog)
            except Exception as e:
                print("Failed when loading cogs.{}: {}".format(cog, e))
                traceback.print_exc()
            else:
                print("-> cogs." + cog)
                logger.info(f'Loaded cog: {cog}.')

        logger.info('Successfully loaded all cogs.')
        print('Successfully loaded all cogs.')

    async def process_close(self):
        logger.info('Shutting down application gracefully.')
        tasks = [
            self.shutdown_application()
        ]

        try:
            await asyncio.gather(*tasks)
        except Exception:
            logger.exception('Exception occured while processing shutdown')
        else:
            logger.info('Graceful shutdown complete.')

    async def close(self):
        await self.process_close()
        await super().close()

    def run(self):
        super().run(os.environ['DISCORD_BOT_TOKEN'])
