"""Coin Runner: a simple 2D platform game made with pygame.

Run, jump, collect coins, stomp enemies, avoid spikes and reach the flag.
Controls: arrow keys or A/D to move, Space/Up/W to jump. Press H in the game for help.
"""

import array
import json
import math
import os

import pygame

import levels
import world as W
from world import TILE

WIDTH, HEIGHT = 960, 560
FPS = 60
HIGHSCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "highscore.json")

LEFT_KEYS = (pygame.K_LEFT, pygame.K_a)
RIGHT_KEYS = (pygame.K_RIGHT, pygame.K_d)
JUMP_KEYS = (pygame.K_SPACE, pygame.K_UP, pygame.K_w)
CONFIRM_KEYS = (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER)

SKY_TOP, SKY_BOTTOM = (92, 170, 235), (200, 232, 250)
DIRT, DIRT_DARK, GRASS = (134, 92, 58), (104, 70, 44), (84, 170, 70)
WHITE, BLACK = (255, 255, 255), (20, 20, 30)
GOLD, GOLD_DARK = (255, 208, 40), (200, 150, 10)
RED, BLUE = (220, 60, 60), (60, 120, 220)


# ---------- High score ----------

def load_highscore(path=HIGHSCORE_FILE):
    try:
        with open(path, "r", encoding="utf-8") as file:
            value = json.load(file)["high_score"]
        return value if isinstance(value, int) and value >= 0 else 0
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def save_highscore(score, path=HIGHSCORE_FILE):
    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"high_score": int(score)}, file)
    except OSError:
        pass            # not being able to save a score must never crash the game


# ---------- Sound (made from simple tones, so no sound files are needed) ----------

def make_tone(notes, volume=0.25, rate=22050, channels=1):
    """notes: list of (frequency in Hz, duration in seconds). Returns raw 16-bit audio."""
    samples = array.array("h")
    for frequency, duration in notes:
        count = int(rate * duration)
        for i in range(count):
            fade = 1 - i / count
            wave = 1 if math.sin(2 * math.pi * frequency * i / rate) >= 0 else -1
            value = int(wave * volume * fade * 32767)
            for _ in range(channels):
                samples.append(value)
    return samples.tobytes()


class Sounds:
    def __init__(self, enabled=True):
        self.enabled = False
        self.muted = False
        self.sounds = {}
        if not enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=1)
            rate, sample_format, channels = pygame.mixer.get_init()
            if sample_format != -16:
                return                      # an unusual audio setup: stay silent rather than risk noise
            recipes = {
                "jump": [(330, 0.05), (440, 0.07)],
                "coin": [(880, 0.05), (1320, 0.09)],
                "stomp": [(200, 0.05), (140, 0.08)],
                "hurt": [(330, 0.08), (220, 0.08), (140, 0.12)],
                "complete": [(523, 0.1), (659, 0.1), (784, 0.1), (1047, 0.2)],
            }
            self.sounds = {name: pygame.mixer.Sound(buffer=make_tone(notes, rate=rate, channels=channels))
                            for name, notes in recipes.items()}
            self.enabled = True
        except (pygame.error, OSError):
            self.enabled = False      # no sound device: the game simply stays silent

    def play(self, name):
        if self.enabled and not self.muted and name in self.sounds:
            self.sounds[name].play()


# ---------- Drawing helpers ----------

def draw_heart(surface, x, y, size, color):
    r = size // 4
    pygame.draw.circle(surface, color, (x + r, y + r), r)
    pygame.draw.circle(surface, color, (x + 3 * r, y + r), r)
    pygame.draw.polygon(surface, color, [(x, y + r + 1), (x + size, y + r + 1), (x + size // 2, y + size)])


def make_sky():
    sky = pygame.Surface((WIDTH, HEIGHT))
    for y in range(HEIGHT):
        t = y / HEIGHT
        color = tuple(int(SKY_TOP[i] + (SKY_BOTTOM[i] - SKY_TOP[i]) * t) for i in range(3))
        pygame.draw.line(sky, color, (0, y), (WIDTH, y))
    return sky


class Game:
    def __init__(self, highscore_path=HIGHSCORE_FILE, sound_enabled=True):
        pygame.font.init()
        self.highscore_path = highscore_path
        self.high_score = load_highscore(highscore_path)
        self.sounds = Sounds(sound_enabled)
        self.fonts = {}
        self.sky = make_sky()
        self.state = "menu"                 # menu, playing, paused, level_complete, game_over, won
        self.level_index = 0
        self.score = 0
        self.lives = W.START_LIVES
        self.level_start = (0, W.START_LIVES)
        self.world = None
        self.jump_pressed = False
        self.new_record = False
        self.show_help = False
        self.time = 0.0
        self.menu_world = W.World(levels.LEVELS[0]["rows"])
        # Load the player character image
        image_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "screenshots",
            "yahya_salman.png"
        )

        self.player_image = pygame.image.load(
            image_path
        ).convert_alpha()

        self.player_image = pygame.transform.scale(
            self.player_image,
            (W.PLAYER_W, W.PLAYER_H)
        )

    # ---------- Game flow ----------

    def start_new_game(self):
        self.level_index = 0
        self.score = 0
        self.lives = W.START_LIVES
        self.new_record = False
        self.load_level()

    def load_level(self):
        self.level_start = (self.score, self.lives)
        self.world = W.World(levels.LEVELS[self.level_index]["rows"], lives=self.lives, score=self.score)
        self.state = "playing"
        self.jump_pressed = False

    def finish_game(self, state):
        self.state = state
        if self.score > self.high_score:
            self.high_score = self.score
            self.new_record = True
            save_highscore(self.score, self.highscore_path)

    def handle_key(self, key):
        """React to a key press. Returns 'quit' when the game should close."""
        if key == pygame.K_m:
            self.sounds.muted = not self.sounds.muted
            return None
        if key == pygame.K_h and self.state in ("menu", "paused"):
            self.show_help = not self.show_help
            return None
        self.show_help = False

        if self.state == "menu":
            if key in CONFIRM_KEYS:
                self.start_new_game()
            elif key == pygame.K_ESCAPE:
                return "quit"
        elif self.state == "playing":
            if key in (pygame.K_ESCAPE, pygame.K_p):
                self.state = "paused"
            elif key in JUMP_KEYS:
                self.jump_pressed = True
        elif self.state == "paused":
            if key in (pygame.K_ESCAPE, pygame.K_p):
                self.state = "playing"
            elif key == pygame.K_r:
                self.score, self.lives = self.level_start
                self.load_level()
            elif key == pygame.K_q:
                self.state = "menu"
        elif self.state == "level_complete":
            if key in CONFIRM_KEYS:
                if self.level_index + 1 < len(levels.LEVELS):
                    self.level_index += 1
                    self.load_level()
                else:
                    self.finish_game("won")
        elif self.state in ("game_over", "won"):
            if key in CONFIRM_KEYS or key == pygame.K_ESCAPE:
                self.state = "menu"
        return None

    def update(self, dt, keys):
        """Advance one frame. `keys` answers keys[pygame.K_x] with True or False."""
        self.time += dt
        if self.state != "playing":
            return
        move = (1 if any(keys[k] for k in RIGHT_KEYS) else 0) - (1 if any(keys[k] for k in LEFT_KEYS) else 0)
        held = any(keys[k] for k in JUMP_KEYS)
        self.world.update(dt, move, self.jump_pressed, held)
        self.jump_pressed = False

        for event in self.world.events:
            self.sounds.play(event)
        self.score, self.lives = self.world.score, self.world.lives
        if self.world.status == "complete":
            self.state = "level_complete"
        elif self.world.status == "game_over":
            self.finish_game("game_over")

    # ---------- Drawing ----------

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = pygame.font.Font(None, size)
        return self.fonts[size]

    def text(self, surface, message, size, color, center=None, topleft=None, topright=None):
        image = self.font(size).render(message, True, color)
        rect = image.get_rect()
        if center:
            rect.center = center
        elif topleft:
            rect.topleft = topleft
        elif topright:
            rect.topright = topright
        shadow = self.font(size).render(message, True, BLACK)
        surface.blit(shadow, rect.move(2, 2))
        surface.blit(image, rect)

    def panel(self, surface, rect, alpha=190):
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(layer, (15, 20, 40, alpha), layer.get_rect(), border_radius=16)
        pygame.draw.rect(layer, (255, 255, 255, 120), layer.get_rect(), width=2, border_radius=16)
        surface.blit(layer, rect.topleft)

    def camera_x(self, w):
        target = w.player.x + W.PLAYER_W / 2 - WIDTH / 2
        return max(0, min(target, max(0, w.width_px - WIDTH)))

    def draw_background(self, surface, cam_x):
        surface.blit(self.sky, (0, 0))
        for layer, (color, base, amp, speed) in enumerate([((120, 190, 140), 430, 50, 0.25), ((90, 160, 110), 480, 40, 0.45)]):
            points = [(0, HEIGHT)]
            for x in range(0, WIDTH + 30, 30):
                y = base - amp * math.sin((x + cam_x * speed) / (110 + 40 * layer)) - amp / 2 * math.sin((x + cam_x * speed) / 47)
                points.append((x, y))
            points.append((WIDTH, HEIGHT))
            pygame.draw.polygon(surface, color, points)
        for i in range(7):
            x = (i * 260 - cam_x * 0.15) % (WIDTH + 300) - 150
            y = 60 + (i * 53) % 130
            for dx, dy, r in [(0, 0, 26), (28, 8, 20), (-28, 10, 18), (10, 14, 22)]:
                pygame.draw.circle(surface, (255, 255, 255), (int(x + dx), int(y + dy)), r)
        self.draw_rumiware(surface) 
        
        
    def draw_rumiware(self, surface):
        font = pygame.font.SysFont("poppins", 64, bold=True)

        text = font.render("RUMIWARE", True, (255, 255, 255))
        text.set_alpha(70)  # Make the text transparent

        rect = text.get_rect(center=(WIDTH // 2, 100))
        surface.blit(text, rect)
    
    
    def draw_world(self, surface, w, cam_x):
        self.draw_background(surface, cam_x)
        first_col = int(cam_x // TILE)
        last_col = int((cam_x + WIDTH) // TILE) + 1

        for c in range(first_col, last_col + 1):
            for r in range(W.ROWS):
                if (c, r) not in w.solids:
                    continue
                rect = pygame.Rect(c * TILE - cam_x, r * TILE, TILE, TILE)
                pygame.draw.rect(surface, DIRT, rect)
                pygame.draw.rect(surface, DIRT_DARK, rect, width=1)
                if (c, r - 1) not in w.solids:
                    pygame.draw.rect(surface, GRASS, (rect.x, rect.y, TILE, 9))
                    pygame.draw.rect(surface, (60, 135, 55), (rect.x, rect.y + 9, TILE, 3))

        for col, row in w.spikes:
            if first_col <= col <= last_col:
                x, y = col * TILE - cam_x, row * TILE
                for i in range(2):
                    left = x + i * TILE / 2
                    pygame.draw.polygon(surface, (200, 205, 215), [(left, y + TILE), (left + TILE / 2, y + TILE), (left + TILE / 4, y + 10)])
                    pygame.draw.polygon(surface, (120, 125, 140), [(left, y + TILE), (left + TILE / 2, y + TILE), (left + TILE / 4, y + 10)], 2)

        col, row = w.flag
        pole_x = col * TILE + TILE / 2 - cam_x
        pygame.draw.rect(surface, (230, 230, 235), (pole_x - 3, (row - 3) * TILE, 6, 4 * TILE))
        wave = math.sin(self.time * 6) * 4
        pygame.draw.polygon(surface, RED, [(pole_x + 3, (row - 3) * TILE), (pole_x + 40, (row - 3) * TILE + 12 + wave), (pole_x + 3, (row - 3) * TILE + 26)])

        for coin in w.coins:
            if coin.collected or not first_col <= coin.col <= last_col:
                continue
            cx = coin.col * TILE + TILE / 2 - cam_x
            cy = coin.row * TILE + TILE / 2 + math.sin(self.time * 4 + coin.col) * 3
            half_width = max(3, abs(math.cos(self.time * 3 + coin.col)) * 11)
            pygame.draw.ellipse(surface, GOLD_DARK, (cx - half_width - 1, cy - 12, 2 * half_width + 2, 24))
            pygame.draw.ellipse(surface, GOLD, (cx - half_width, cy - 11, 2 * half_width, 22))

        for enemy in w.enemies:
            if enemy.alive:
                x, y = enemy.x - cam_x, enemy.y
                squash = math.sin(self.time * 8 + enemy.x) * 2
                body = pygame.Rect(x, y + 4 + squash, W.ENEMY_W, W.ENEMY_H - 4 - squash)
                pygame.draw.ellipse(surface, (150, 60, 190), body)
                pygame.draw.ellipse(surface, (90, 30, 120), body, 2)
                for eye_x in (x + 9, x + 21):
                    pygame.draw.circle(surface, WHITE, (int(eye_x), int(y + 12)), 4)
                    pygame.draw.circle(surface, BLACK, (int(eye_x + enemy.direction * 1.5), int(y + 12)), 2)

        self.draw_player(surface, w, cam_x)

    def draw_player(self, surface, w, cam_x):
            p = w.player
    
            if p.invulnerable > 0 and int(self.time * 12) % 2 == 0:
                return
    
            image = self.player_image
    
            if p.facing < 0:
                image = pygame.transform.flip(
                    self.player_image, True, False
                )
    
            # Position the bigger image so its feet align
            # with the bottom of the original player hitbox.
            screen_x = round(p.x - cam_x)
            screen_y = round(p.y + W.PLAYER_H - image.get_height())
    
            surface.blit(image, (screen_x, screen_y))
        
        
    def draw_hud(self, surface, w):
        bar = pygame.Surface((WIDTH, 40), pygame.SRCALPHA)
        bar.fill((10, 15, 35, 150))
        surface.blit(bar, (0, 0))
        name = levels.LEVELS[self.level_index]["name"]
        self.text(surface, f"Level {self.level_index + 1}: {name}", 26, WHITE, topleft=(12, 10))
        self.text(surface, f"Coins {w.coins_collected}/{w.total_coins}", 26, GOLD, center=(430, 21))
        self.text(surface, f"Score {w.score}", 26, WHITE, center=(580, 21))
        self.text(surface, f"Best {max(self.high_score, w.score)}", 26, (180, 200, 255), center=(715, 21))
        for i in range(max(0, w.lives)):
            draw_heart(surface, WIDTH - 40 - i * 32, 9, 24, RED)

    def draw_help(self, surface):
        rect = pygame.Rect(WIDTH // 2 - 280, 110, 560, 330)
        self.panel(surface, rect, 225)
        self.text(surface, "How to play", 44, GOLD, center=(WIDTH // 2, 145))
        lines = ["Move: arrow keys or A / D", "Jump: Space, Up or W (hold to jump higher)",
                "Collect coins, reach the flag at the end of each level",
                "Jump on enemies to defeat them, spikes and sides hurt",
                "Falling into a pit costs a life", "P or Esc: pause     M: mute sound",
                "Press any key to close this help"]
        for i, line in enumerate(lines):
            self.text(surface, line, 28, WHITE, center=(WIDTH // 2, 195 + i * 36))

    def draw(self, surface):
        if self.state == "menu":
            cam = (self.time * 90) % max(1, self.menu_world.width_px - WIDTH)
            self.draw_world(surface, self.menu_world, cam)
            self.panel(surface, pygame.Rect(WIDTH // 2 - 290, 90, 580, 360))
            self.text(surface, "COIN RUNNER", 96, GOLD, center=(WIDTH // 2, 160))
            self.text(surface, "A 2D platform adventure", 32, WHITE, center=(WIDTH // 2, 215))
            if int(self.time * 2) % 2 == 0:
                self.text(surface, "Press Enter to start", 42, WHITE, center=(WIDTH // 2, 290))
            self.text(surface, "Move: arrows or A/D     Jump: Space", 28, (200, 220, 255), center=(WIDTH // 2, 345))
            self.text(surface, "H: help     M: mute     Esc: quit", 28, (200, 220, 255), center=(WIDTH // 2, 380))
            self.text(surface, f"High score: {self.high_score}", 32, GOLD, center=(WIDTH // 2, 425))
            if self.show_help:
                self.draw_help(surface)
            return

        self.draw_world(surface, self.world, self.camera_x(self.world))
        self.draw_hud(surface, self.world)

        if self.state == "paused":
            self.panel(surface, pygame.Rect(WIDTH // 2 - 220, 170, 440, 200))
            self.text(surface, "PAUSED", 70, WHITE, center=(WIDTH // 2, 215))
            self.text(surface, "P / Esc: resume     R: restart level", 28, WHITE, center=(WIDTH // 2, 280))
            self.text(surface, "H: help     Q: back to menu", 28, WHITE, center=(WIDTH // 2, 315))
            if self.show_help:
                self.draw_help(surface)
        elif self.state == "level_complete":
            w = self.world
            self.panel(surface, pygame.Rect(WIDTH // 2 - 260, 120, 520, 310))
            self.text(surface, "LEVEL COMPLETE!", 64, GOLD, center=(WIDTH // 2, 170))
            self.text(surface, f"Coins collected: {w.coins_collected} / {w.total_coins}", 34, WHITE, center=(WIDTH // 2, 235))
            self.text(surface, f"Level bonus: +{w.level_bonus}", 34, WHITE, center=(WIDTH // 2, 275))
            if w.total_coins > 0 and w.coins_collected == w.total_coins:
                self.text(surface, "All coins found!", 30, GOLD, center=(WIDTH // 2, 310))
            self.text(surface, f"Score: {w.score}", 40, WHITE, center=(WIDTH // 2, 355))
            last = self.level_index + 1 >= len(levels.LEVELS)
            self.text(surface, "Press Enter to finish" if last else "Press Enter for the next level", 30, (200, 220, 255), center=(WIDTH // 2, 400))
        elif self.state in ("game_over", "won"):
            self.panel(surface, pygame.Rect(WIDTH // 2 - 260, 130, 520, 290))
            if self.state == "won":
                self.text(surface, "YOU WIN!", 80, GOLD, center=(WIDTH // 2, 190))
                self.text(surface, "You finished every level.", 32, WHITE, center=(WIDTH // 2, 245))
            else:
                self.text(surface, "GAME OVER", 80, RED, center=(WIDTH // 2, 190))
                self.text(surface, "You ran out of lives.", 32, WHITE, center=(WIDTH // 2, 245))
            self.text(surface, f"Final score: {self.score}", 44, WHITE, center=(WIDTH // 2, 300))
            if self.new_record:
                self.text(surface, "New high score!", 36, GOLD, center=(WIDTH // 2, 345))
            else:
                self.text(surface, f"High score: {self.high_score}", 32, (180, 200, 255), center=(WIDTH // 2, 345))
            self.text(surface, "Press Enter to return to the menu", 28, (200, 220, 255), center=(WIDTH // 2, 390))


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Coin Runner")
    clock = pygame.time.Clock()
    game = Game()

    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000, 1 / 30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if game.handle_key(event.key) == "quit":
                    running = False
        game.update(dt, pygame.key.get_pressed())
        game.draw(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
