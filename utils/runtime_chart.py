"""Render observations without treating missing samples as downtime."""
from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from data.texts.stats import CHART_LABELS, CHART_LABELS_FALLBACK

COLORS = {0: "#506580", 1: "#3fb950", 2: "#d9a441", 3: "#f85149"}
BACKGROUND, EMPTY, TEXT = "#0d1117", "#21262d", "#e6edf3"
SAMPLE_SECONDS = 300


def _fonts():
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return [ImageFont.truetype(name, size) for size in (28, 18, 15)], CHART_LABELS
        except OSError:
            pass
    return [ImageFont.load_default(size=size) for size in (28, 18, 15)], CHART_LABELS_FALLBACK


def _samples(observations, component, now):
    samples = {}
    for row in observations:
        if row.component != component or row.bucket_at > now or row.status not in COLORS:
            continue
        previous = samples.get(row.bucket_at)
        if previous is None or getattr(row, "observed_at", row.bucket_at) >= getattr(previous, "observed_at", previous.bucket_at):
            samples[row.bucket_at] = row
    return samples


def runtime_summary(observations, component, now, *, seconds=86400):
    """Estimate durations from five-minute buckets; keep unobserved time separate."""
    samples = _samples(observations, component, now)
    durations = {state: 0 for state in COLORS}
    for stamp, row in samples.items():
        overlap = max(0, min(now, stamp + SAMPLE_SECONDS) - max(now - seconds, stamp))
        durations[row.status] += overlap
    active = durations[1] + durations[2] + durations[3]
    latest = max(samples.values(), key=lambda row: getattr(row, "observed_at", row.bucket_at), default=None)
    current = None
    if latest is not None and 0 <= now - getattr(latest, "observed_at", latest.bucket_at) <= 180:
        current = 0 if not latest.expected else 1 if latest.available == latest.expected else 2 if latest.available else 3
    return dict(good=durations[1], issues=durations[2] + durations[3], disabled=durations[0],
                unknown=max(0, seconds - sum(durations.values())),
                percent=100 * durations[1] / active if active else None, current=current, latest=latest)


def format_duration(seconds, labels=CHART_LABELS):
    minutes = max(0, int(seconds) // 60)
    if not minutes:
        return labels["less_minute"]
    days, rest = divmod(minutes, 1440)
    hours, minutes = divmod(rest, 60)
    return " ".join(f"{value} {unit}" for value, unit in zip((days, hours, minutes), labels["units"]) if value)


def render_runtime_chart(observations, offset, now, *, uptime_seconds=None):
    observations = list(observations)
    fonts, labels = _fonts()
    tz = timezone(timedelta(hours=offset))
    current = datetime.fromtimestamp(now, tz)
    midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    earliest = min((datetime.fromtimestamp(row.bucket_at, tz).date() for row in observations
                    if now - 14 * 86400 <= row.bucket_at <= now), default=current.date())
    days = min(14, max(3, (current.date() - earliest).days + 1))
    first_day = midnight - timedelta(days=days - 1)
    section_height = 158 + days * 26
    footer = 138 + section_height * 2
    image = Image.new("RGB", (1120, footer + 132), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((38, 22), labels["title"], font=fonts[0], fill=TEXT)
    draw.text((38, 62), f"{first_day:%d.%m} - {current:%d.%m.%Y %H:%M}   UTC{offset:+d}", font=fonts[1], fill="#9da7b3")
    if uptime_seconds is not None:
        draw.text((38, 94), labels["process"].format(duration=format_duration(uptime_seconds, labels)),
                  font=fonts[1], fill=TEXT)

    for index, component in enumerate(("bot", "userbot")):
        top = 138 + index * section_height
        samples = _samples(observations, component, now)
        summary = runtime_summary(observations, component, now)
        state, latest = summary["current"], summary["latest"]
        status = labels["stale"]
        if state is not None:
            if component == "userbot" and state in (1, 2):
                status = labels["all_accounts"].format(available=latest.available, expected=latest.expected)
            else:
                status = labels[{0: "off", 1: "ready", 2: "partial", 3: "down"}[state]]
        draw.text((38, top), labels[component], font=fonts[1], fill=TEXT)
        draw.text((38, top + 28), labels["now"].format(status=status), font=fonts[1], fill=COLORS.get(state, "#9da7b3"))
        daily = labels["daily"].format(percent=f"{summary['percent']:.1f}%") if summary["percent"] is not None else labels["no_percent"]
        draw.text((38, top + 57), daily, font=fonts[1], fill=TEXT)
        parts = [labels[name].format(duration=format_duration(summary[name], labels))
                 for name in ("good", "issues", "unknown", "disabled") if summary[name] > 0]
        draw.text((38, top + 86), "  |  ".join(parts), font=fonts[2], fill="#9da7b3")
        for hour in range(24):
            draw.text((119 + hour * 40, top + 115), f"{hour:02}", font=fonts[2], fill="#9da7b3")
        for day in range(days):
            date = first_day + timedelta(days=day)
            y = top + 143 + day * 26
            draw.text((38, y + 1), f"{date:%d.%m}", font=fonts[2], fill=TEXT if date.date() == current.date() else "#9da7b3")
            for hour in range(24):
                x = 116 + hour * 40
                start = int(date.replace(hour=hour).timestamp())
                draw.rounded_rectangle((x, y, x + 35, y + 18), radius=3,
                                       fill=EMPTY if start <= now else BACKGROUND, outline=EMPTY)
                # One bad interval must not paint an entire hour red.
                for slot in range(12):
                    row = samples.get(start + slot * SAMPLE_SECONDS)
                    if row is not None:
                        left = x + slot * 3
                        draw.rectangle((left, y + 1, left + 2, y + 17), fill=COLORS[row.status])
    for index, (state, name) in enumerate(labels["legend"]):
        x, y = 38 + (index % 3) * 350, footer + (index // 3) * 30
        draw.rounded_rectangle((x, y, x + 16, y + 16), radius=3, fill=COLORS.get(state, EMPTY))
        draw.text((x + 26, y - 1), name, font=fonts[2], fill=TEXT)
    draw.text((38, footer + 70), labels["coverage"], font=fonts[2], fill="#9da7b3")
    draw.text((38, footer + 97), labels["estimate"], font=fonts[2], fill="#9da7b3")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
