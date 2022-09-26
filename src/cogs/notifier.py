from discord.ext import commands


class NotifierCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command()
    async def ping(self, ctx):
        await ctx.send('Pong!')


async def setup(bot):
    await bot.add_cog(NotifierCog(bot))
