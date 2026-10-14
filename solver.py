"""Level playability checker.

A simple computer player that looks a little way into the future, using the
real game physics, and picks the best action. If it can finish a level, the
level is possible to finish.

Run it with:  python solver.py
It takes about half a minute, and saves the winning runs in replays.json,
which the automated tests play back. Run it again after you change a level.
"""

import copy
import json
import os
import sys

import levels
import world

DT = 1 / 60
LOOKAHEAD_FRAMES = 75
REPLAN_EVERY = 6


def clone(w):
    """A cheap copy of the world (the solid tiles are shared, they never change)."""
    c = copy.copy(w)
    c.player = copy.copy(w.player)
    c.enemies = [copy.copy(e) for e in w.enemies]
    c.coins = [copy.copy(coin) for coin in w.coins]
    c.events = []
    return c


def make_plans():
    """Each plan is a list of (move, jump_pressed, jump_held) for LOOKAHEAD_FRAMES frames."""
    plans = []
    for run_frames in (LOOKAHEAD_FRAMES, 40, 28, 20, 12):
        for jump_hold in (None, 5, 10, 16, 24, 40):
            frames = []
            for i in range(LOOKAHEAD_FRAMES):
                move = 1 if i < run_frames else 0
                if jump_hold is None:
                    frames.append((move, False, False))
                else:
                    frames.append((move, i == 0, i < jump_hold))
            plans.append(frames)
    # stand still variants (to wait for an enemy to pass)
    plans.append([(0, False, False)] * LOOKAHEAD_FRAMES)
    return plans


PLANS = make_plans()


def score_plan(start, plan):
    w = clone(start)
    lives = w.lives
    for move, pressed, held in plan:
        w.update(DT, move, pressed, held)
        if w.status != "playing":
            break
    if w.status == "complete":
        return 1_000_000 - w.time
    if w.lives < lives or w.status == "game_over":
        return -100_000 + w.player.x
    return w.player.x + 3 * (w.coins_collected - start.coins_collected) + (20 if w.player.on_ground else 0)


def solve(level_index, max_seconds=150, verbose=False):
    w = world.World(levels.LEVELS[level_index]["rows"])
    script = []                         # every frame's inputs, so a run can be replayed
    active = []
    frame = 0
    while w.status == "playing" and w.time < max_seconds:
        if not active or (w.player.on_ground and frame % REPLAN_EVERY == 0 and len(active) < LOOKAHEAD_FRAMES - 2):
            best = max(PLANS, key=lambda plan: score_plan(w, plan))
            active = list(best)
        move, pressed, held = active.pop(0)
        script.append((move, pressed, held))
        w.update(DT, move, pressed, held)
        frame += 1
    return w, script


REPLAY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replays.json")


def compress(script):
    """Store the run compactly: [how many frames, move, jump pressed, jump held] per change."""
    packed = []
    for frame in script:
        if packed and packed[-1][1:] == list(frame):
            packed[-1][0] += 1
        else:
            packed.append([1, *frame])
    return packed


def replay(level_index, packed):
    """Play back a recorded run in the real game world and return the world."""
    w = world.World(levels.LEVELS[level_index]["rows"])
    for count, move, pressed, held in packed:
        for i in range(count):
            w.update(DT, move, bool(pressed) and i == 0, bool(held))
    return w


def record_all():
    """Solve every level and save the winning runs, so tests can replay them quickly."""
    data = {}
    for i, level in enumerate(levels.LEVELS):
        w, script = solve(i)
        print(f"{level['name']}: {w.status}  time {w.time:.1f}s  lives left {w.lives}  "
                f"coins {w.coins_collected}/{w.total_coins}")
        if w.status != "complete":
            print("  This level could not be finished by the computer player. It may be too hard or impossible.")
            return False
        data[level["name"]] = compress(script)
    with open(REPLAY_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file)
    print(f"Saved {REPLAY_FILE}")
    return True


if __name__ == "__main__":
    sys.exit(0 if record_all() else 1)
