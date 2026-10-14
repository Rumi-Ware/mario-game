"""Automated tests. Run with:  python -m unittest -v

They check the physics, the rules, every level (a recorded computer-player run must still
finish each one) and the game screens. No window or sound device is needed.
"""

import collections
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")      # run without opening a window
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")      # and without a sound device

import pygame

import levels
import platformer as pf
import solver
import world as W
from world import TILE, ROWS, PLAYER_W, PLAYER_H

DT = 1 / 60
GROUND_TOP = 12 * TILE
STAND_Y = GROUND_TOP - PLAYER_H


def make_rows(width=40, gap=None, extras=None):
    """A flat test level: ground on rows 12-13, player on column 2, flag on the last-but-one column."""
    grid = [["."] * width for _ in range(ROWS)]
    for col in range(width):
        if gap and gap[0] <= col < gap[1]:
            continue
        grid[12][col] = grid[13][col] = "#"
    grid[11][2] = "P"
    grid[11][width - 2] = "F"
    for (col, row), char in (extras or {}).items():
        grid[row][col] = char
    return ["".join(row) for row in grid]


def settled(extras=None, **kwargs):
    """A test world where the player is already standing on the ground."""
    w = W.World(make_rows(extras=extras, **kwargs))
    for _ in range(5):
        w.update(DT)
    assert w.player.on_ground
    return w


def run(w, frames, move=0, jump_first=False, held=False):
    events = []
    for i in range(frames):
        w.update(DT, move, jump_first and i == 0, held)
        events += w.events
    return events


class LevelTests(unittest.TestCase):
    def test_there_are_three_levels(self):
        self.assertEqual(len(levels.LEVELS), 3)
        names = [level["name"] for level in levels.LEVELS]
        self.assertEqual(len(set(names)), 3)

    def test_every_level_is_valid(self):
        for level in levels.LEVELS:
            w = W.World(level["rows"])
            self.assertEqual(len(level["rows"]), ROWS, level["name"])
            self.assertGreater(w.total_coins, 15, level["name"])
            self.assertGreaterEqual(len(w.enemies), 2, level["name"])

    def test_player_starts_on_solid_ground(self):
        for level in levels.LEVELS:
            w = W.World(level["rows"])
            col, row = w.start
            self.assertTrue(w.solid_at(col, row + 1), level["name"])

    def test_enemies_and_spikes_stand_on_solid_blocks(self):
        for level in levels.LEVELS:
            rows = level["rows"]
            for r, line in enumerate(rows):
                for c, char in enumerate(line):
                    if char in "E^":
                        self.assertEqual(rows[r + 1][c], "#", f"{level['name']}: {char} at column {c + 1}, row {r + 1}")

    def test_bad_maps_are_rejected(self):
        good = make_rows()
        bad_maps = {
            "too few rows": good[:-1],
            "uneven rows": good[:-1] + [good[-1] + "#"],
            "no start": [row.replace("P", ".") for row in good],
            "two starts": [row.replace("F", "P") for row in good],
            "no flag": [row.replace("F", ".") for row in good],
            "unknown symbol": [good[0].replace(".", "?", 1)] + good[1:],
        }
        for name, rows in bad_maps.items():
            with self.assertRaises(W.LevelError, msg=name):
                W.World(rows)


class MovementTests(unittest.TestCase):
    def test_player_falls_and_lands(self):
        w = W.World(make_rows())
        w.player.y = 100
        run(w, 90)
        self.assertTrue(w.player.on_ground)
        self.assertAlmostEqual(w.player.y, STAND_Y, places=3)

    def test_walking_speed(self):
        w = settled()
        x0 = w.player.x
        run(w, 30, move=1)
        self.assertAlmostEqual(w.player.x - x0, W.MOVE_SPEED * 0.5, delta=2)
        self.assertEqual(w.player.facing, 1)
        run(w, 10, move=-1)
        self.assertEqual(w.player.facing, -1)

    def test_walls_stop_the_player(self):
        w = settled({(8, 10): "#", (8, 11): "#"})
        run(w, 240, move=1)
        self.assertAlmostEqual(w.player.x + PLAYER_W, 8 * TILE, places=3)

    def test_cannot_leave_the_left_edge(self):
        w = settled()
        run(w, 300, move=-1)
        self.assertEqual(w.player.x, 0)

    def test_jump_height(self):
        w = settled()
        top = w.player.y
        for i in range(60):
            w.update(DT, 0, i == 0, True)
            top = min(top, w.player.y)
        rise = STAND_Y - top
        self.assertGreater(rise, 3 * TILE)              # clears three tiles
        self.assertLess(rise, 3.5 * TILE)

    def test_short_tap_jumps_lower(self):
        w = settled()
        top = w.player.y
        for i in range(60):
            w.update(DT, 0, i == 0, i < 4)
            top = min(top, w.player.y)
        self.assertLess(STAND_Y - top, 2 * TILE)              # a hop, not a full jump
        self.assertGreater(STAND_Y - top, 5)

    def test_no_double_jump(self):
        w = settled()
        w.update(DT, 0, True, True)
        events = run(w, 10, held=True)
        events += run(w, 1, jump_first=True, held=True)       # press again in mid-air
        events += run(w, 15, held=True)
        self.assertEqual(events.count("jump"), 0)             # the only jump was the first one

    def test_head_bump(self):
        w = settled({(2, 8): "#", (3, 8): "#"})
        top = w.player.y
        for i in range(60):
            w.update(DT, 0, i == 0, True)
            top = min(top, w.player.y)
        self.assertGreaterEqual(top, 9 * TILE - 1e-6)

    def test_coyote_time_allows_a_late_jump(self):
        for wait_frames, should_jump in [(3, True), (14, False)]:
            w = settled(gap=(6, 40))
            while w.player.on_ground:
                w.update(DT, 1)
            run(w, wait_frames, move=1)
            events = run(w, 1, move=1, jump_first=True, held=True)
            self.assertEqual("jump" in events, should_jump, f"waited {wait_frames} frames")

    def test_jump_buffer_allows_an_early_press(self):
        w = settled()
        w.update(DT, 0, True, True)
        while not (w.player.vy > 0 and w.player.y > STAND_Y - 12):
            w.update(DT, 0, False, True)
        events = run(w, 8, jump_first=True, held=True)        # pressed just before landing
        self.assertIn("jump", events)
        self.assertLess(w.player.vy, 0)


class PickupTests(unittest.TestCase):
    def test_coins_are_collected_once(self):
        w = settled({(5, 11): "o", (6, 11): "o"})
        events = run(w, 90, move=1)
        self.assertEqual(w.coins_collected, 2)
        self.assertEqual(w.score, 2 * W.COIN_POINTS)
        self.assertEqual(events.count("coin"), 2)
        run(w, 30, move=-1)
        run(w, 30, move=1)
        self.assertEqual(w.score, 2 * W.COIN_POINTS)

    def test_flag_completes_the_level(self):
        w = settled()
        events = run(w, 600, move=1)
        self.assertEqual(w.status, "complete")
        self.assertIn("complete", events)
        self.assertEqual(w.level_bonus, W.LEVEL_POINTS)

    def test_bonus_for_collecting_every_coin(self):
        w = settled({(5, 11): "o"})
        run(w, 600, move=1)
        self.assertEqual(w.status, "complete")
        self.assertEqual(w.level_bonus, W.LEVEL_POINTS + W.ALL_COINS_BONUS)
        self.assertEqual(w.score, W.COIN_POINTS + W.LEVEL_POINTS + W.ALL_COINS_BONUS)

    def test_tall_flag_cannot_be_jumped_over(self):
        w = settled()
        flag_col = w.flag[0]
        w.player.x = (flag_col - 3) * TILE
        for i in range(120):
            w.update(DT, 1, i % 30 == 0, True)               # keep jumping toward the flag
            if w.status == "complete":
                break
        self.assertEqual(w.status, "complete")


class HazardTests(unittest.TestCase):
    def test_spikes_hurt_once_then_protect_briefly(self):
        w = settled({(6, 11): "^"})
        events = run(w, 60, move=1)
        self.assertEqual(w.lives, W.START_LIVES - 1)
        self.assertIn("hurt", events)
        self.assertGreater(w.player.invulnerable, 0)
        run(w, 30, move=1)                                    # pressing on does not hurt again
        self.assertEqual(w.lives, W.START_LIVES - 1)

    def test_falling_into_a_pit_costs_a_life_and_returns_to_safe_ground(self):
        w = settled(gap=(8, 14))
        for _ in range(300):                                  # walk right until the fall costs a life
            w.update(DT, 1)
            if "hurt" in w.events:
                break
        self.assertEqual(w.lives, W.START_LIVES - 1)
        self.assertLess(w.player.x, 8 * TILE)                 # back on the safe side of the pit
        run(w, 30)
        self.assertTrue(w.player.on_ground)
        self.assertEqual(w.status, "playing")

    def test_game_over_when_lives_run_out(self):
        w = settled({(6, 11): "^"})
        w.lives = 1
        run(w, 60, move=1)
        self.assertEqual(w.status, "game_over")
        time_then = w.time
        run(w, 10, move=1)
        self.assertEqual(w.time, time_then)                   # the world stops after game over

    def test_stomping_an_enemy(self):
        with mock.patch.object(W, "ENEMY_SPEED", 0.0):
            w = settled({(10, 11): "E"})
            enemy = w.enemies[0]
            w.player.x = enemy.x + (W.ENEMY_W - PLAYER_W) / 2
            w.player.y = enemy.y - 120
            w.player.on_ground = False
            events = run(w, 60)
            self.assertFalse(enemy.alive)
            self.assertIn("stomp", events)
            self.assertEqual(w.score, W.ENEMY_POINTS)
            self.assertEqual(w.lives, W.START_LIVES)

    def test_touching_an_enemy_from_the_side_hurts(self):
        with mock.patch.object(W, "ENEMY_SPEED", 0.0):
            w = settled({(8, 11): "E"})
            for _ in range(120):                              # walk right until the enemy is touched
                w.update(DT, 1)
                if "hurt" in w.events:
                    break
            self.assertTrue(w.enemies[0].alive)
            self.assertEqual(w.lives, W.START_LIVES - 1)
            run(w, 15)                                        # the knockback pushes you back
            self.assertLess(w.player.x + PLAYER_W, w.enemies[0].x)

    def test_enemies_turn_at_walls_and_ledges_and_never_fall(self):
        rows = make_rows(extras={(10, 11): "E"}, gap=(0, 0))
        grid = [list(row) for row in rows]
        for c in range(0, 40):                       # a short island: columns 8-14 only
            if not 8 <= c <= 14:
                grid[12][c] = grid[13][c] = "."
        grid[11][2] = "."
        grid[11][9] = "P"
        w = W.World(["".join(row) for row in grid])
        enemy = w.enemies[0]
        directions = set()
        for _ in range(900):
            w.update(DT)
            directions.add(enemy.direction)
            self.assertGreaterEqual(enemy.x, 8 * TILE - 1)
            self.assertLessEqual(enemy.x + W.ENEMY_W, 15 * TILE + 1)
        self.assertEqual(directions, {-1, 1})
        self.assertAlmostEqual(enemy.y, GROUND_TOP - W.ENEMY_H, places=3)


class PlayabilityTests(unittest.TestCase):
    """Every level must be finishable. A computer player recorded a winning run for each level
    (python solver.py); here the runs are played back in the real game world."""

    def test_every_level_can_be_finished_by_the_recorded_runs(self):
        with open(solver.REPLAY_FILE, encoding="utf-8") as file:
            recorded = json.load(file)
        for index, level in enumerate(levels.LEVELS):
            self.assertIn(level["name"], recorded, f"No recorded run for {level['name']}. Run: python solver.py")
            w = solver.replay(index, recorded[level["name"]])
            self.assertEqual(w.status, "complete",
                            f"{level['name']} changed and the recorded run no longer finishes it. Run: python solver.py")

    @unittest.skipUnless(os.environ.get("RUN_SLOW_TESTS"), "slow: set RUN_SLOW_TESTS=1 to run the solver live")
    def test_solver_can_finish_every_level_live(self):
        for index, level in enumerate(levels.LEVELS):
            w, script = solver.solve(index)
            self.assertEqual(w.status, "complete", level["name"])


class FakeKeys(collections.defaultdict):
    def __init__(self):
        super().__init__(bool)


class GameTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, "highscore.json")
        self.game = pf.Game(highscore_path=self.path, sound_enabled=False)
        self.surface = pygame.Surface((pf.WIDTH, pf.HEIGHT))
        self.keys = FakeKeys()

    def tearDown(self):
        self.folder.cleanup()

    def start(self):
        self.game.handle_key(pygame.K_RETURN)

    def reach_flag(self):
        w = self.game.world
        col, row = w.flag
        w.player.x, w.player.y = col * TILE + 6, (row + 1) * TILE - PLAYER_H
        self.game.update(DT, self.keys)

    def test_menu_to_game_and_back(self):
        self.assertEqual(self.game.state, "menu")
        self.start()
        self.assertEqual(self.game.state, "playing")
        self.assertEqual(self.game.lives, W.START_LIVES)

    def test_escape_quits_only_from_the_menu(self):
        self.assertEqual(self.game.handle_key(pygame.K_ESCAPE), "quit")
        self.start()
        self.assertIsNone(self.game.handle_key(pygame.K_ESCAPE))
        self.assertEqual(self.game.state, "paused")

    def test_pause_and_resume(self):
        self.start()
        self.game.handle_key(pygame.K_p)
        self.assertEqual(self.game.state, "paused")
        x = self.game.world.player.x
        self.keys[pygame.K_RIGHT] = True
        self.game.update(DT, self.keys)
        self.assertEqual(self.game.world.player.x, x)         # nothing moves while paused
        self.game.handle_key(pygame.K_p)
        self.assertEqual(self.game.state, "playing")

    def test_keys_move_and_jump(self):
        self.start()
        for _ in range(10):
            self.game.update(DT, self.keys)
        x = self.game.world.player.x
        self.keys[pygame.K_d] = True
        for _ in range(20):
            self.game.update(DT, self.keys)
        self.assertGreater(self.game.world.player.x, x)
        self.keys[pygame.K_SPACE] = True
        self.game.handle_key(pygame.K_SPACE)
        self.game.update(DT, self.keys)
        self.assertLess(self.game.world.player.vy, 0)

    def test_restart_level_from_pause_resets_progress(self):
        self.start()
        self.game.world.score = 500
        self.game.world.lives = 1
        self.game.handle_key(pygame.K_p)
        self.game.handle_key(pygame.K_r)
        self.assertEqual((self.game.world.score, self.game.world.lives), (0, W.START_LIVES))

    def test_finishing_all_levels_wins_and_saves_the_high_score(self):
        self.start()
        for index in range(len(levels.LEVELS)):
            self.reach_flag()
            self.assertEqual(self.game.state, "level_complete")
            self.game.handle_key(pygame.K_RETURN)
            if index < len(levels.LEVELS) - 1:
                self.assertEqual(self.game.state, "playing")
                self.assertEqual(self.game.level_index, index + 1)
        self.assertEqual(self.game.state, "won")
        self.assertGreaterEqual(self.game.score, 3 * W.LEVEL_POINTS)
        self.assertTrue(self.game.new_record)
        self.assertEqual(pf.load_highscore(self.path), self.game.score)
        self.game.handle_key(pygame.K_RETURN)
        self.assertEqual(self.game.state, "menu")

    def test_game_over_screen(self):
        self.start()
        self.game.world.lives = 1
        self.game.world.player.y = 5000                       # fall out of the world
        self.game.update(DT, self.keys)
        self.assertEqual(self.game.state, "game_over")
        self.game.handle_key(pygame.K_RETURN)
        self.assertEqual(self.game.state, "menu")

    def test_lower_score_does_not_replace_the_high_score(self):
        pf.save_highscore(9999, self.path)
        game = pf.Game(highscore_path=self.path, sound_enabled=False)
        game.start_new_game()
        game.world.lives = 1
        game.world.player.y = 5000
        game.update(DT, self.keys)
        self.assertFalse(game.new_record)
        self.assertEqual(pf.load_highscore(self.path), 9999)

    def test_all_screens_can_be_drawn(self):
        self.game.draw(self.surface)                          # menu
        self.game.handle_key(pygame.K_h)
        self.game.draw(self.surface)                          # menu with help
        self.game.handle_key(pygame.K_h)
        self.start()
        for _ in range(30):
            self.game.update(DT, self.keys)
        self.game.draw(self.surface)                          # playing
        self.game.handle_key(pygame.K_p)
        self.game.draw(self.surface)                          # paused
        self.game.handle_key(pygame.K_h)
        self.game.draw(self.surface)                          # paused with help
        self.game.handle_key(pygame.K_p)
        self.reach_flag()
        self.game.draw(self.surface)                          # level complete
        self.game.state = "won"
        self.game.draw(self.surface)
        self.game.state = "game_over"
        self.game.draw(self.surface)

    def test_every_level_can_be_drawn_at_the_start_and_end(self):
        for level in levels.LEVELS:
            w = W.World(level["rows"])
            self.game.level_index = levels.LEVELS.index(level)
            for cam in (0, w.width_px - pf.WIDTH):
                self.game.draw_world(self.surface, w, cam)
                self.game.draw_hud(self.surface, w)

    def test_mute_toggle(self):
        self.assertFalse(self.game.sounds.muted)
        self.game.handle_key(pygame.K_m)
        self.assertTrue(self.game.sounds.muted)
        self.game.handle_key(pygame.K_m)
        self.assertFalse(self.game.sounds.muted)


class HighScoreAndSoundTests(unittest.TestCase):
    def test_high_score_file_handling(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "highscore.json")
            self.assertEqual(pf.load_highscore(path), 0)              # missing file
            pf.save_highscore(1230, path)
            self.assertEqual(pf.load_highscore(path), 1230)
            for broken in ["not json", '{"high_score": "lots"}', '{"high_score": -5}', "[]", "{}"]:
                with open(path, "w") as file:
                    file.write(broken)
                self.assertEqual(pf.load_highscore(path), 0, broken)

    def test_saving_to_an_impossible_place_does_not_crash(self):
        pf.save_highscore(10, os.path.join(tempfile.gettempdir(), "no_such_folder_xyz", "hs.json"))

    def test_tone_maker(self):
        data = pf.make_tone([(440, 0.1), (880, 0.05)], rate=22050)
        self.assertEqual(len(data), (int(22050 * 0.1) + int(22050 * 0.05)) * 2)
        stereo = pf.make_tone([(440, 0.1)], rate=44100, channels=2)
        self.assertEqual(len(stereo), int(44100 * 0.1) * 2 * 2)

    def test_game_works_with_sound_switched_on(self):
        pygame.mixer.quit()
        game = pf.Game(highscore_path=os.devnull, sound_enabled=True)
        game.sounds.play("jump")                                       # must never crash
        game.sounds.play("not_a_sound")

    def test_sounds_match_the_audio_device_settings(self):
        """pygame.init() opens the mixer as 44100 Hz stereo; the tones must be built to match,
        otherwise they would play at the wrong pitch."""
        pygame.mixer.quit()
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
        sounds = pf.Sounds(True)
        self.assertTrue(sounds.enabled)
        self.assertAlmostEqual(sounds.sounds["jump"].get_length(), 0.12, delta=0.02)
        sounds.muted = True
        sounds.play("jump")                                            # muted: silently ignored


if __name__ == "__main__":
    unittest.main()
