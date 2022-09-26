import asyncio
from bot import OWNotifierBot

try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

if __name__ == '__main__':
    bot = OWNotifierBot()
    bot.run()
