"""Which moments of a video become keyframes. Pure arithmetic over scene-change times; ffmpeg is not involved here.

Rules: one frame near the start; scene changes at least `min_gap_ms` apart; an extra frame whenever `max_gap_ms` would pass
without one; at most `max_count` in all. Over the cap, the frame whose neighbours are closest together goes first (a filler before a scene change).
"""

import math
from collections.abc import Sequence

END_MARGIN_MS = 100  # the last decodable frame sits slightly before the container duration
OPENING_MS = 300  # not frame 0: fades from black are common


def select_keyframe_times(
    scene_changes_ms: Sequence[int], duration_ms: int, *, min_gap_ms: int = 1000, max_gap_ms: int = 4000,
    max_count: int = 16,
) -> list[int]:
    if duration_ms <= 0 or max_count < 1:
        return []
    last = max(0, duration_ms - END_MARGIN_MS)
    first = min(OPENING_MS, last)
    scenes: set[int] = set()
    picked = [first]
    for t in sorted(scene_changes_ms):
        if 0 < t <= last and t - picked[-1] >= min_gap_ms:
            picked.append(t)
            scenes.add(t)
    # fill: a boundary at the end of the clip (not a frame) closes the last gap
    filled: list[int] = []
    for a, b in zip(picked, [*picked[1:], duration_ms]):
        filled.append(a)
        gap = b - a
        if gap > max_gap_ms:
            parts = math.ceil(gap / max_gap_ms)
            filled += [min(last, a + round(gap * i / parts)) for i in range(1, parts)]
    times = sorted(set(filled))
    while len(times) > max_count:  # max_count >= 1 here, so at least two frames remain to choose from
        victim = min(
            range(1, len(times)),
            key=lambda i: ((times[i + 1] if i + 1 < len(times) else duration_ms) - times[i - 1], times[i] in scenes),
        )
        times.pop(victim)
    return times
