from discord.ext import commands

from bot import config


class TrustedUserRequired(commands.CheckFailure):
    pass


async def is_trusted_user(ctx):
    if ctx.author.id in config.ADMIN_IDS:
        return True

    permissions = getattr(ctx.author, "guild_permissions", None)
    if permissions and permissions.administrator:
        return True

    return await ctx.bot.is_owner(ctx.author)


async def trusted_user_required(ctx):
    if await is_trusted_user(ctx):
        return True

    raise TrustedUserRequired("This command is limited to trusted users.")


trusted_only = commands.check(trusted_user_required)
