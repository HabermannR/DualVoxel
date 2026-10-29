"""The orbit camera of the render dock: it circles a target in the renderer's world units."""
import math

import numpy as np

FOV_TAN = math.tan(math.radians(22.5))  # the renderer's perspective view: 45 degrees from top to bottom


class OrbitCamera:
    """Orbits a target in the renderer's world units (32 voxels are 1). Orthographic (ortho), it looks along
    the same line with parallel rays, ortho_height world units from the view's centre to its top edge."""

    def __init__(self):
        self.target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.yaw = math.radians(200)
        self.pitch = math.radians(15)
        self.distance = 3.0
        self.ortho = False
        self.ortho_height = self.distance * FOV_TAN
        self.reach = 1.0  # the framed model's longest side: an orthographic eye stands clear of it
        self.pos = np.zeros(3, dtype=np.float32)
        self.fwd = np.zeros(3, dtype=np.float32)
        self.right = np.zeros(3, dtype=np.float32)
        self.up = np.zeros(3, dtype=np.float32)
        self.update_vectors()

    def frame(self, centre, size):
        """Aim at a model: centre and longest side in world units."""
        self.target = np.array(centre, dtype=np.float32)
        self.distance = max(0.3, 1.45 * size)
        self.ortho_height = self.distance * FOV_TAN  # the same picture of the model either way
        self.reach = max(0.3, float(size))
        self.update_vectors()

    def set_ortho(self, ortho: bool):
        """Switch between perspective and parallel rays, keeping the model as large as it was at the target."""
        ortho = bool(ortho)
        if ortho and not self.ortho:
            self.ortho_height = self.distance * FOV_TAN
        elif self.ortho and not ortho:
            self.distance = max(0.2, self.ortho_height / FOV_TAN)
        self.ortho = ortho
        self.update_vectors()

    @property
    def view_distance(self) -> float:
        """How far a perspective eye would stand to see what the view shows at the target."""
        return self.ortho_height / FOV_TAN if self.ortho else self.distance

    def update_vectors(self):
        # Parallel rays start on the plane through the eye: it stands back far enough to see all the model.
        distance = max(self.distance, 2 * self.reach) if self.ortho else self.distance
        self.pos[0] = self.target[0] + distance * math.cos(self.pitch) * math.sin(self.yaw)
        self.pos[1] = self.target[1] + distance * math.cos(self.pitch) * math.cos(self.yaw)
        self.pos[2] = self.target[2] + distance * math.sin(self.pitch)
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
        s = self.view_distance * 0.0015
        self.target -= self.right * dx * s
        self.target += self.up * dy * s
        self.update_vectors()

    def zoom(self, amount):
        if self.ortho:  # no eye to bring nearer: the view itself narrows
            self.ortho_height = max(0.2 * FOV_TAN, self.ortho_height * (0.9 ** amount))
        else:
            self.distance = max(0.2, self.distance * (0.9 ** amount))
        self.update_vectors()
