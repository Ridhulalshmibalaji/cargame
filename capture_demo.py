import pygame
from main import NeonDriftGame

pygame.init()
game = NeonDriftGame()
game.start_round()

for _ in range(90):
    game.update()

game.draw()
pygame.image.save(game.screen, "highway_play.png")
pygame.quit()
print("Saved highway_play.png")
