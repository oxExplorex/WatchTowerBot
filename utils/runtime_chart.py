"""Render synthetic status cells locally; no archive content or external service."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from data.texts.stats import CHART_LABELS, CHART_LABELS_FALLBACK

COLORS = {0: "#506580", 1: "#3fb950", 2: "#d9a441", 3: "#f85149"}
BACKGROUND, EMPTY, TEXT = "#0d1117", "#21262d", "#e6edf3"


def _fonts():
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return [ImageFont.truetype(name, size) for size in (28, 18, 15)], CHART_LABELS
        except OSError:
            pass
    return [ImageFont.load_default(size=size) for size in (28, 18, 15)], CHART_LABELS_FALLBACK


def render_runtime_chart(observations, offset, now):
    fonts, labels = _fonts()
    tz = timezone(timedelta(hours=offset))
    current = datetime.fromtimestamp(now, tz)
    first_day = current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=13)
    cells = defaultdict(list)
    for row in observations:
        if row.bucket_at <= now:
            local = datetime.fromtimestamp(row.bucket_at, tz)
            cells[(row.component, local.date(), local.hour)].append(row)
    image = Image.new("RGB", (1120, 1110), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((38, 25), "WatchTowerBot", font=fonts[0], fill=TEXT)
    draw.text((38, 65), f"{first_day:%d.%m} - {current:%d.%m.%Y}   UTC{offset:+d}", font=fonts[1], fill=TEXT)
    for index, component in enumerate(("bot", "userbot")):
        top = 112 + index * 442
        draw.text((38, top), labels[component], font=fonts[1], fill=TEXT)
        for hour in range(24):
            draw.text((145 + hour * 38, top + 34), f"{hour:02}", font=fonts[2], fill="#9da7b3")
        for day in range(14):
            date = first_day + timedelta(days=day)
            y = top + 61 + day * 24
            draw.text((38, y + 1), f"{date:%d.%m}", font=fonts[2], fill="#9da7b3")
            for hour in range(24):
                x = 143 + hour * 38
                start = int(date.replace(hour=hour).timestamp())
                values = cells[(component, date.date(), hour)]
                draw.rounded_rectangle((x, y, x + 29, y + 18), radius=3,
                                       fill=EMPTY if start <= now else BACKGROUND, outline=EMPTY)
                if values:
                    expected = min(12, max(1, (now - start) // 300 + 1))
                    coverage = min(1, len({row.bucket_at for row in values}) / expected)
                    height = max(2, round(16 * coverage))
                    draw.rounded_rectangle((x + 1, y + 18 - height, x + 28, y + 17), radius=2,
                                           fill=COLORS[max(row.status for row in values)])
    for index, (state, name) in enumerate(labels["legend"]):
        x, y = 38 + (index % 3) * 350, 1006 + (index // 3) * 34
        draw.rounded_rectangle((x, y, x + 18, y + 18), radius=3, fill=COLORS.get(state, EMPTY))
        draw.text((x + 28, y - 1), name, font=fonts[2], fill=TEXT)
    draw.text((38, 1081), labels["coverage"], font=fonts[2], fill="#9da7b3")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
