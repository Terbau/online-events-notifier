# flake8: noqa

import re
import sys
import discord
import asyncio
import traceback

podium_emojies = {
    1: '🥇',
    2: '🥈',
    3: '🥉',
}

emojies = {
    'a': '🇦', 'b': '🇧', 'c': '🇨', 'd': '🇩',
    'e': '🇪', 'f': '🇫', 'g': '🇬', 'h': '🇭',
    'i': '🇮', 'j': '🇯', 'k': '🇰', 'l': '🇱',
	'm': '🇲', 'n': '🇳', 'o': '🇴', 'p': '🇵',
	'q': '🇶', 'r': '🇷', 's': '🇸', 't': '🇹',
	'u': '🇺', 'v': '🇻', 'w': '🇼', 'x': '🇽',
	'y': '🇾', 'z': '🇿', 0: '0️⃣', 1: '1️⃣',
	2: '2️⃣', 3: '3️⃣', 4: '4️⃣', 5: '5️⃣',
	6: '6️⃣', 7: '7️⃣', 8: '8️⃣', 9: '9️⃣',
	10: '🔟', '#': '#️⃣', '*': '*️⃣',
	'!': '❗', '?': '❓',
}


def get_color_from_hex_string(string):
    fixed = re.sub(r'[^0-9a-fA-F]', '', string)
    return discord.Color(int(fixed, 16))


def parse_time(delta, **kwargs):
    _t = {}
    s = int(delta.total_seconds())
    _t['years'], remainder = divmod(s, (525600 * 60))
    _t['months'], remainder = divmod(remainder, (43800 * 60))
    _t['weeks'], remainder = divmod(remainder, (10080 * 60))
    _t['days'], remainder = divmod(remainder, (1440 * 60))
    _t['hours'], remainder = divmod(remainder, (60 * 60))
    _t['minutes'], _t['seconds'] = divmod(remainder, (1 * 60))

    _msg = []
    for name, time in _t.items():
        if kwargs.get(name, False):
            if time == 0:
                continue
            elif time == 1:
                _msg.append(f"{time} {name[:1]}")
            else:
                _msg.append(f"{time} {name}")
    return _msg


def strftime(dt, timezone=False):
    t = dt.strftime("%Y-%m-%d %H:%M:%S")

    if timezone:
        tzinfo = dt.tzinfo
        if tzinfo is not None:
            tz = tzinfo.tzname(dt)
            t = f'{t} {tz}'

    return t


def escape_discord_formatting(message, escape_new_lines=True):
    escape_strings = (
        ">",
        "*",
        "_",
        "~",
        "`",
    )
    message = re.sub(f"([{'|'.join(escape_strings)}])", r"\\\g<1>", message)

    if escape_discord_formatting:
        message = message.replace("\n", " ")
    return message


def get_scoreboard_emoji(num, podium=True):
    if podium and num in podium_emojies:
        return podium_emojies[num]

    parts = [emojies[int(n)] for n in str(num)]
    return ''.join(parts)


def get_as_table_display(entries, max_chars=None, strip=False):
    if not entries:
        return (
            '+-----------------+\n'
            '|      Empty      |\n'
            '+-----------------+'
        )

    if not isinstance(entries, list):
        entries = [entries]

    entriess = entries
    entries = []
    for i in range(len(entriess)):
        entries.append({'*'*len(str(len(entriess))): str(i+1), **entriess[i]})  # noqa

    spl = '|' if not strip else ''
    column_width = {k: max(len(str(x[k])) for x in (entries + [{k:k}])) for k in entries[0].keys()}  # noqa
    header = spl + spl.join(f' {str(n):<{w}} ' for n, w in column_width.items()) + spl  # noqa
    breaker = '+' + '+'.join('-' * (w+2) for w in column_width.values()) + '+'  # noqa
    header_breaker = '+' + '+'.join('=' * (w+2) for w in column_width.values()) + '+'  # noqa

    output = []
    if not strip:
        output.append(header_breaker)
    output.append(header)
    if not strip:
        output.append(header_breaker)

    for entry in entries:
        ap = []
        for v, w in zip(entry.values(), column_width.values()):
            ap.append(f' {str(v):<{w}} ')

        output.append(spl + spl.join(ap) + spl)
        if not strip:
            output.append(breaker)

    res = '\n'.join(output)
    if max_chars and len(res) > max_chars:
        if strip:
            return res
        return get_as_table_display(entries, strip=True)

    return res


def tracebacked_callback(future):
    try:
        error = future.exception()
    except asyncio.InvalidStateError:
        pass
    except asyncio.CancelledError:
        pass
    else:
        if isinstance(error, asyncio.CancelledError):
            return

        elif error is not None:
            print('Ignoring exception in task', file=sys.stderr)
            traceback.print_exception(
                type(error),
                error,
                error.__traceback__,
                file=sys.stderr
            )


def create_tracebacked_task(*args, **kwargs):
    loop = kwargs.pop('loop', None) or asyncio.get_event_loop()
    task = loop.create_task(*args, **kwargs)
    task.add_done_callback(tracebacked_callback)
    return task


def cmp_embeds(a: discord.Embed, b: discord.Embed, *, exclude: list = []):
    attrs = ('title', 'description', '_colour', '_timestamp',
             'url', 'thumbnail', 'author', 'image')
    for attr in attrs:
        if attr.strip('_') in exclude:
            continue

        if getattr(a, attr, None) != getattr(b, attr, None):
            return False

    if 'footer' not in exclude and a.footer.text != b.footer.text:
        return False
    if 'fields' not in exclude:
        a_fields = getattr(a, '_fields', [])
        b_fields = getattr(b, '_fields', [])
        if len(a_fields) != len(b_fields):
            return False
        
        for c, a_field in enumerate(a_fields):
            b_field = b_fields[c]

            if a_field['name'] != b_field['name']:
                return False
            if a_field['value'] != b_field['value']:
                return False
            if a_field['inline'] != b_field['inline']:
                return False


class LockEvent(asyncio.Lock):
    def __init__(self) -> None:
        super().__init__()

        self._event = asyncio.Event()
        self._event.set()
        self.wait = self._event.wait
        self.priority = 0

    async def acquire(self) -> None:
        await super().acquire()
        self._event.clear()

    def release(self) -> None:
        super().release()

        # Only set if no new acquire waiters exists. This is because we
        # don't want any wait()'s to return if there immediately will
        # be a new acquirer.
        if not (self._waiters is not None and [w for w in self._waiters
                                               if not w.cancelled()]):
            self._event.set()
            self.priority = 0
