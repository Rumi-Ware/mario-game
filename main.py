
import asyncio
import pygame

from platformer import Game, WIDTH, HEIGHT, FPS


async def main():
    pygame.init()

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Coin Runner")

    clock = pygame.time.Clock()
    game = Game(sound_enabled=False)
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

        # Let the browser process other tasks.
        await asyncio.sleep(0)

    pygame.quit()

asyncio.create_task(main())
