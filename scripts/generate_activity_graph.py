#!/usr/bin/env python3
"""Build a self-contained SVG of the latest 31 days of public GitHub contributions.

The source is GitHub's public contribution-calendar fragment:
https://github.com/users/anubhab7105/contributions

No API token or third-party chart-rendering service is required.
"""
from __future__ import annotations

import argparse
import html
import math
import re
import sys
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USERNAME = "anubhab7105"
CALENDAR_URL = f"https://github.com/users/{USERNAME}/contributions"
DAYS = 31


def contribution_count(text: str) -> int | None:
    """Extract an exact contribution count from GitHub tooltip/label text."""
    normalized = " ".join(html.unescape(text).split())
    if re.search(r"\bno contributions\b", normalized, re.IGNORECASE):
        return 0
    match = re.search(r"\b([\d,]+)\s+contributions?\b", normalized, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


class CalendarParser(HTMLParser):
    """Extract dated contribution cells and their corresponding tooltips."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cells: dict[str, dict[str, str | int | None]] = {}
        self.tooltips: dict[str, str] = {}
        self._active_tooltip: str | None = None
        self._tooltip_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)

        if "data-date" in attributes:
            day = attributes.get("data-date") or ""
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                direct_count = contribution_count(
                    " ".join(
                        str(attributes.get(name) or "")
                        for name in ("data-count", "aria-label", "title")
                    )
                )
                raw_count = attributes.get("data-count")
                if direct_count is None and raw_count is not None:
                    try:
                        direct_count = int(raw_count)
                    except ValueError:
                        pass

                self.cells[day] = {
                    "id": attributes.get("id"),
                    "count": direct_count,
                    "level": attributes.get("data-level"),
                }

        if tag.lower() == "tool-tip":
            self._active_tooltip = attributes.get("for") or attributes.get("id")
            self._tooltip_parts = []

    def handle_data(self, data: str) -> None:
        if self._active_tooltip is not None:
            self._tooltip_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "tool-tip" and self._active_tooltip is not None:
            self.tooltips[self._active_tooltip] = " ".join(self._tooltip_parts)
            self._active_tooltip = None
            self._tooltip_parts = []


def parse_calendar(markup: str) -> dict[date, int]:
    parser = CalendarParser()
    parser.feed(markup)

    counts: dict[date, int] = {}
    for day_text, cell in parser.cells.items():
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue

        count = cell["count"]
        if count is None:
            cell_id = cell["id"]
            tooltip = parser.tooltips.get(str(cell_id), "") if cell_id else ""
            count = contribution_count(tooltip)

        # GitHub's level 0 explicitly means no contributions, so zero is safe.
        if count is None and str(cell["level"]) == "0":
            count = 0

        if count is not None:
            counts[day] = max(0, int(count))

    if len(counts) < 20:
        raise ValueError(
            "Could not read enough daily contribution counts from GitHub's public "
            "calendar. The upstream HTML may have changed; refusing to publish a "
            "misleading graph."
        )
    return counts


def fetch_calendar() -> str:
    request = Request(
        CALENDAR_URL,
        headers={
            "User-Agent": "AnubhabDas-ProfileActivityGraph/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            if response.status != 200:
                raise RuntimeError(f"GitHub calendar returned HTTP {response.status}")
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to fetch the public GitHub calendar: {exc}") from exc


def svg_text(value: object) -> str:
    return html.escape(str(value), quote=True)


def build_svg(all_counts: dict[date, int], today: date | None = None) -> str:
    today = today or date.today()
    eligible = [day for day in all_counts if day <= today]
    if not eligible:
        raise ValueError("The public contribution calendar contains no recent dates.")

    end_day = max(eligible)
    start_day = end_day - timedelta(days=DAYS - 1)
    days = [start_day + timedelta(days=offset) for offset in range(DAYS)]
    values: list[int] = []
    missing: list[str] = []
    for day in days:
        if day in all_counts:
            values.append(all_counts[day])
        elif day > end_day:
            values.append(0)
        else:
            missing.append(day.isoformat())
            values.append(0)

    # A short gap in the source calendar is acceptable only when it is outside
    # the visible window. Recent missing days otherwise indicate a bad scrape.
    if missing:
        raise ValueError(f"Contribution counts missing from visible range: {', '.join(missing)}")

    total = sum(values)
    active_days = sum(value > 0 for value in values)
    peak = max(values, default=0)
    y_max = max(4, int(math.ceil(peak / 4) * 4))
    y_step = max(1, y_max // 4)

    width, height = 1200, 350
    left, right, top, bottom = 76, 34, 110, 274
    plot_width = width - left - right
    plot_height = bottom - top
    x_step = plot_width / (DAYS - 1)

    def x_at(index: int) -> float:
        return left + index * x_step

    def y_at(value: int) -> float:
        return bottom - (value / y_max) * plot_height

    line_points = [(x_at(index), y_at(value)) for index, value in enumerate(values)]
    line_path = " ".join(
        ("M" if index == 0 else "L") + f" {x:.2f} {y:.2f}"
        for index, (x, y) in enumerate(line_points)
    )
    area_path = (
        f"M {line_points[0][0]:.2f} {bottom} "
        + " ".join(f"L {x:.2f} {y:.2f}" for x, y in line_points)
        + f" L {line_points[-1][0]:.2f} {bottom} Z"
    )

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 350" width="1200" height="350" role="img" aria-labelledby="chart-title chart-desc">',
        '<title id="chart-title">Anubhab Das GitHub contribution activity</title>',
        f'<desc id="chart-desc">Daily public GitHub contribution counts for the 31 days ending {svg_text(end_day.isoformat())}. Total: {total}. Active days: {active_days}.</desc>',
        '<defs><linearGradient id="area-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#06B6D4" stop-opacity="0.34"/><stop offset="100%" stop-color="#06B6D4" stop-opacity="0.015"/></linearGradient></defs>',
        '<rect width="1200" height="350" rx="18" fill="#0D1117"/>',
        '<rect x="0.5" y="0.5" width="1199" height="349" rx="17.5" fill="none" stroke="#30363D"/>',
        '<text x="34" y="42" fill="#F0F6FC" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="22" font-weight="700">GITHUB ACTIVITY</text>',
        f'<text x="34" y="67" fill="#8B949E" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="13">Daily contributions · {svg_text(start_day.strftime("%b %d"))} – {svg_text(end_day.strftime("%b %d, %Y"))}</text>',
        f'<text x="1166" y="36" text-anchor="end" fill="#22D3EE" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="17" font-weight="700">{total:,} contributions</text>',
        f'<text x="1166" y="58" text-anchor="end" fill="#8B949E" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="12">{active_days} active days · peak {peak}/day</text>',
    ]

    for tick in range(5):
        value = tick * y_step
        y = y_at(value)
        parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#30363D" stroke-width="1" stroke-dasharray="3 6"/>'
        )
        parts.append(
            f'<text x="{left-16}" y="{y+4:.2f}" text-anchor="end" fill="#8B949E" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="11">{value}</text>'
        )

    parts.append(f'<path d="{area_path}" fill="url(#area-fill)"/>')
    parts.append(f'<path d="{line_path}" fill="none" stroke="#22D3EE" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')

    for index, (x, y) in enumerate(line_points):
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.2" fill="#0D1117" stroke="#67E8F9" stroke-width="1.8"><title>{svg_text(days[index].isoformat())}: {values[index]} contribution{"s" if values[index] != 1 else ""}</title></circle>'
        )

    label_indices = sorted(set([0, 7, 14, 21, 30]))
    for index in label_indices:
        label = days[index].strftime("%b %d")
        anchor = "start" if index == 0 else ("end" if index == DAYS - 1 else "middle")
        parts.append(
            f'<text x="{x_at(index):.2f}" y="304" text-anchor="{anchor}" fill="#8B949E" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="12">{svg_text(label)}</text>'
        )

    parts.extend(
        [
            '<line x1="34" y1="320" x2="1166" y2="320" stroke="#21262D"/>',
            '<text x="34" y="338" fill="#6E7681" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="10">PUBLIC CONTRIBUTION CALENDAR</text>',
            '<text x="1166" y="338" text-anchor="end" fill="#6E7681" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="10">AUTO-UPDATED BY GITHUB ACTIONS</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist/activity-graph.svg", help="Path to the generated SVG")
    parser.add_argument("--input-html", help="Optional local HTML fixture for offline testing")
    args = parser.parse_args()

    try:
        markup = (
            Path(args.input_html).read_text(encoding="utf-8")
            if args.input_html
            else fetch_calendar()
        )
        counts = parse_calendar(markup)
        svg = build_svg(counts)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(svg, encoding="utf-8")
        print(f"Generated {output} from {len(counts)} parsed contribution days.")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
