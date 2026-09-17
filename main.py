import random

import pygame

from config.settings import SETTINGS

from game.background import MorningBackground, NeonBackground
from game.arena import Road
from game.car import Car
from game.collision import boxes_overlap
from game.ui import GameUI
from game.theme import PLAYER_COLOR, ENEMY_COLOR, TRAFFIC_COLORS

from ai.population import Population

from training.trainer import Trainer
from training.fitness import (
    ChaseStats,
    build_enemy_inputs,
    pursuit_steer,
)

from persistence.checkpoint import CheckpointManager

from utils.logger import setup_logger


logger = setup_logger()


class TrafficCar:

    def __init__(self, x, y, speed):

        self.x = x
        self.y = y
        self.speed = speed
        self.color = random.choice(TRAFFIC_COLORS)
        self.width = 28
        self.height = 46

    def update(self, player_speed):

        self.y += player_speed - self.speed

    def get_rect(self):

        return pygame.Rect(
            int(self.x - self.width // 2),
            int(self.y - self.height // 2),
            self.width,
            self.height,
        )

    def draw(self, screen):

        cx = int(self.x)
        cy = int(self.y)
        w = self.width
        h = self.height

        x = cx - w // 2
        y_top = cy - h // 2

        # Drop shadow
        shadow_surf = pygame.Surface((w + 8, h + 8), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow_surf, (0, 0, 0, 70), (0, 0, w + 8, h + 8))
        screen.blit(shadow_surf, (x - 4, y_top + 4))

        # Wheels
        wheel_w, wheel_h = 4, 9
        wheel_color = (25, 25, 28)
        for wx, wy in [
            (x - 2, y_top + 5),
            (x + w - 2, y_top + 5),
            (x - 2, y_top + h - 13),
            (x + w - 2, y_top + h - 13),
        ]:
            pygame.draw.rect(screen, wheel_color, (wx, wy, wheel_w, wheel_h), border_radius=2)

        # Body
        pygame.draw.rect(screen, self.color, (x, y_top, w, h), border_radius=6)

        # Cabin / Windows
        roof_w = w - 6
        roof_h = h - 20
        roof_x = x + 3
        roof_y = y_top + 10

        pygame.draw.rect(screen, (32, 38, 48), (roof_x, roof_y, roof_w, roof_h), border_radius=3)
        pygame.draw.rect(screen, (150, 200, 235), (roof_x + 2, roof_y + 2, roof_w - 4, 6), border_radius=2)
        pygame.draw.rect(screen, (110, 160, 195), (roof_x + 2, roof_y + roof_h - 6, roof_w - 4, 4), border_radius=2)

        # Taillights (facing player moving up)
        pygame.draw.rect(screen, (220, 40, 40), (x + 2, y_top + h - 3, 5, 3))
        pygame.draw.rect(screen, (220, 40, 40), (x + w - 7, y_top + h - 3, 5, 3))

    def is_off_screen(self, road):

        return self.y > road.bottom + 40 or self.y < road.top - 60


class NeonDriftGame:

    STATE_MENU = "menu"
    STATE_PLAYING = "playing"
    STATE_CRASHING = "crashing"
    STATE_GAME_OVER = "game_over"

    PLAYER_Y = 560

    def __init__(self):

        pygame.init()

        self.screen = pygame.display.set_mode(
            (SETTINGS.WIDTH, SETTINGS.HEIGHT)
        )

        pygame.display.set_caption("Morning Pursuit — AI Highway Chase")

        self.clock = pygame.time.Clock()

        self.background = MorningBackground()
        self.road = Road()
        self.ui = GameUI()

        self.population = Population()
        self.trainer = Trainer(self.population)
        self.checkpoints = CheckpointManager()

        self.active_genome = self.population.get_best()

        self.player = None
        self.enemy = None
        self.chase_stats = None
        self.enemy_gap = SETTINGS.START_GAP
        self.traffic = []
        self.end_reason = "caught"

        self.state = self.STATE_MENU
        self.best_distance = 0.0
        self.session_distance = 0.0
        self.crash_flash = False

        self._spawn_actors()

    def _pick_hunter(self):

        elites = sorted(
            self.population.genomes,
            key=lambda g: g.fitness,
            reverse=True,
        )[:5]

        if random.random() < 0.2:
            return random.choice(elites)

        return elites[0]

    def _spawn_traffic(self):

        self.traffic = []

        lane_w = self.road.width / SETTINGS.LANE_COUNT

        for _ in range(6):

            lane = random.randint(0, SETTINGS.LANE_COUNT - 1)

            x = self.road.left + lane_w * lane + lane_w / 2

            y = random.uniform(
                self.road.top + 40,
                self.road.bottom - 80,
            )

            speed = random.uniform(3.8, 5.4)

            self.traffic.append(TrafficCar(x, y, speed))

    def _spawn_actors(self):

        lane_w = self.road.width / SETTINGS.LANE_COUNT
        center_lane = self.road.left + lane_w * 1.5

        self.player = Car(center_lane - 50, color=PLAYER_COLOR)

        self.enemy = Car(
            center_lane + 50,
            color=ENEMY_COLOR,
            max_speed=SETTINGS.ENEMY_MAX_SPEED,
        )

        self.chase_stats = ChaseStats()
        self.enemy_gap = SETTINGS.START_GAP
        self.session_distance = 0.0
        self.crash_flash = False

        self._spawn_traffic()

    def start_round(self):

        self._spawn_actors()
        self.active_genome = self._pick_hunter()
        self.state = self.STATE_PLAYING

    def _update_traffic(self):

        for car in self.traffic:
            car.update(self.player.speed)

        for car in self.traffic:

            if car.is_off_screen(self.road):

                lane_w = self.road.width / SETTINGS.LANE_COUNT
                lane = random.randint(0, SETTINGS.LANE_COUNT - 1)

                car.x = self.road.left + lane_w * lane + lane_w / 2
                car.y = self.road.top - random.uniform(20, 140)
                car.speed = random.uniform(3.8, 5.4)
                car.color = random.choice(TRAFFIC_COLORS)

    def _pursuit_blend(self):

        gen = self.population.generation

        return max(
            0.0,
            SETTINGS.PURSUIT_BLEND_START * (1.0 - (gen - 1) / 20.0),
        )

    def _apply_catch_up(self):

        if self.enemy_gap > SETTINGS.CATCH_UP_GAP:

            boost = min(2.2, (self.enemy_gap - SETTINGS.CATCH_UP_GAP) * 0.01)

            self.enemy.speed = min(
                self.enemy.max_speed + 1.5,
                self.enemy.speed + boost * 0.08,
            )

    def _update_enemy_ai(self):

        inputs = build_enemy_inputs(
            self.enemy,
            self.player,
            self.enemy_gap,
            self.road,
        )

        output = self.active_genome.network.forward(inputs)

        nn_steer = float(output[0])
        throttle = float(output[1])

        blend = self._pursuit_blend()
        steer = pursuit_steer(self.enemy, self.player, self.road)

        final_steer = blend * steer + (1.0 - blend) * nn_steer

        self.enemy.apply_ai_controls(final_steer, throttle)

        self._apply_catch_up()

    def _check_traffic_collision(self):

        player_rect = self.player.get_rect(self.PLAYER_Y)

        for traffic in self.traffic:

            if boxes_overlap(
                self.player.x,
                self.PLAYER_Y,
                self.player.width,
                self.player.height,
                traffic.x,
                traffic.y,
                traffic.width,
                traffic.height,
            ):

                self.player.apply_crash(traffic.x)
                self.crash_flash = True
                self.end_reason = "crash"
                self.chase_stats.player_crashed = True
                self.state = self.STATE_CRASHING

                return True

        return False

    def _chase_metrics(self):

        lateral_sep = abs(self.player.x - self.enemy.x)

        chase_distance = (
            self.enemy_gap ** 2 + lateral_sep ** 2
        ) ** 0.5

        return chase_distance, lateral_sep

    def update(self):

        if self.state == self.STATE_CRASHING:

            self.player.x += self.player.lateral
            self.player.lateral *= 0.8
            self.player.x = self.road.clamp_x(self.player.x)

            if self.player.update_crash():
                self._end_round()

            return

        if self.state != self.STATE_PLAYING:
            return

        keys = pygame.key.get_pressed()

        self.player.apply_player_controls(keys)
        self.player.move(self.road)

        self._update_enemy_ai()
        self.enemy.move(self.road)

        self.road.scroll_by(self.player.speed)

        self.enemy_gap -= self.enemy.speed - self.player.speed
        self.enemy_gap = max(SETTINGS.MIN_GAP, self.enemy_gap)

        self._update_traffic()

        if self._check_traffic_collision():
            return

        self.session_distance = self.player.distance_travelled

        chase_distance, lateral_sep = self._chase_metrics()

        self.chase_stats.update(
            chase_distance,
            self.enemy_gap,
            lateral_sep,
        )

        if (
            lateral_sep < 34
            and self.enemy_gap <= SETTINGS.CATCH_RADIUS
        ):

            self.chase_stats.caught = True
            self.chase_stats.catch_time = self.chase_stats.session_time
            self.end_reason = "caught"
            self._end_round()

    def _end_round(self):

        self.state = self.STATE_GAME_OVER

        self.best_distance = max(
            self.best_distance,
            self.session_distance,
        )

        self.trainer.score_enemy(
            self.active_genome,
            self.chase_stats,
        )

        logger.info(
            f"Round over ({self.end_reason}) | "
            f"Dist: {self.session_distance:.0f} | "
            f"AI fitness: {self.active_genome.fitness:.0f} | "
            f"Min gap: {self.chase_stats.min_gap:.0f} | "
            f"Gen: {self.population.generation}"
        )

        if self.population.generation % 3 == 0:
            self.checkpoints.save(
                self.population.get_best(),
                self.population.generation,
            )

        self.trainer.evolve()
        self.active_genome = self._pick_hunter()

        logger.info(
            f"AI evolved → Generation {self.population.generation} | "
            f"Best fitness: {self.population.get_best().fitness:.0f}"
        )

    def _on_restart(self):

        self.start_round()

    def _handle_events(self):

        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                return False

            if event.type == pygame.KEYDOWN:

                if event.key == pygame.K_ESCAPE:
                    return False

                if event.key == pygame.K_SPACE:

                    if self.state == self.STATE_MENU:
                        self.start_round()

                    elif self.state == self.STATE_GAME_OVER:
                        self._on_restart()

            if event.type == pygame.MOUSEBUTTONDOWN:

                if (
                    self.state == self.STATE_GAME_OVER
                    and self.ui.is_restart_clicked(event.pos)
                ):
                    self._on_restart()

        return True

    def draw(self):

        self.background.draw(self.screen)
        self.road.draw(self.screen)

        if self.state in (
            self.STATE_PLAYING,
            self.STATE_CRASHING,
            self.STATE_GAME_OVER,
        ):

            for car in self.traffic:
                car.draw(self.screen)

            enemy_y = self.PLAYER_Y + self.enemy_gap

            self.enemy.draw(self.screen, enemy_y)
            self.player.draw(
                self.screen,
                self.PLAYER_Y,
                flash=self.crash_flash,
            )

            chase_distance, _ = self._chase_metrics()

            threat = max(
                0,
                min(
                    100,
                    int(
                        (1.0 - chase_distance / SETTINGS.THREAT_DISTANCE)
                        * 100
                    ),
                ),
            )

            self.ui.draw_hud(
                self.screen,
                self.session_distance,
                self.player.speed,
                self.best_distance,
                self.population.generation,
                chase_distance,
                threat,
            )

            self.ui.draw_controls_hint(self.screen)

        if self.state == self.STATE_MENU:
            self.ui.draw_start_overlay(self.screen)

        if self.state == self.STATE_GAME_OVER:

            self.ui.draw_game_over(
                self.screen,
                self.session_distance,
                self.population.generation,
                self.end_reason,
                self.active_genome.fitness,
            )

        pygame.display.flip()

    def run(self):

        running = True

        while running:

            running = self._handle_events()
            self.update()
            self.draw()
            self.clock.tick(SETTINGS.FPS)

        pygame.quit()


if __name__ == "__main__":

    game = NeonDriftGame()
    game.run()
