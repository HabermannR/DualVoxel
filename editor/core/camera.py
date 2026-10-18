"""The orbit camera of the render dock: it circles a target in the renderer's world units."""
import math

import numpy as np


class OrbitCamera:
    """Orbits a target in the renderer's world units (32 voxels are 1)."""

    def __init__(self):
        self.target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.yaw = math.radians(200)
        self.pitch = math.radians(15)
        self.distance = 3.0
        self.pos = np.zeros(3, dtype=np.float32)
        self.fwd = np.zeros(3, dtype=np.float32)
        self.right = np.zeros(3, dtype=np.float32)
        self.up = np.zeros(3, dtype=np.float32)
        self.update_vectors()

    def frame(self, centre, size):
        """Aim at a model: centre and longest side in world units."""
        self.target = np.array(centre, dtype=np.float32)
        self.distance = max(0.3, 1.45 * size)
        self.update_vectors()

    def update_vectors(self):
        self.pos[0] = self.target[0] + self.distance * math.cos(self.pitch) * math.sin(self.yaw)
        self.pos[1] = self.target[1] + self.distance * math.cos(self.pitch) * math.cos(self.yaw)
        self.pos[2] = self.target[2] + self.distance * math.sin(self.pitch)
        self.fwd = self.target - self.pos
        self.fwd /= np.linalg.norm(self.fwd)
        world_up = np.array([0, 0, 1], dtype=np.float32)
        self.right = np.cross(self.fwd, world_up)
        self.right /= np.linalg.norm(self.right)
        self.up = np.cross(self.right, self.fwd)

    def rotate(self, dx, dy):
        self.yaw += dx * 0.01
        self.pitch = max(-1.4, min(1.4, self.pitch + dy * 0.01))
        self.update_vectors()

    def pan(self, dx, dy):
        s = self.distance * 0.0015
        self.target -= self.right * dx * s
        self.target += self.up * dy * s
        self.update_vectors()

    def zoom(self, amount):
        self.distance = max(0.2, self.distance * (0.9 ** amount))
        self.update_vectors()
