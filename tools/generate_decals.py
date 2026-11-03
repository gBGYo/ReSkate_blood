"""Generate editable blood decals with a simplified, volume-accounted fluid model.

Standalone artwork tool; does not build or install game assets. See decal_lab/README.md.
"""

import argparse
from dataclasses import asdict, dataclass, fields, replace
import json
import math
from pathlib import Path
import sys

try:
    import numpy as np
    from PIL import Image, ImageDraw
    from scipy.ndimage import binary_erosion, binary_fill_holes, gaussian_filter, gaussian_filter1d, label, map_coordinates
except ImportError as error:
    raise SystemExit("Use the .venv-decal-lab environment; see tools/decal_lab/README.md for uv setup.") from error


ROOT = Path(__file__).resolve().parents[1]
KINDS = ("splash", "smear", "pool", "drops")
MODEL_VERSION = 1


@dataclass(frozen=True)
class Recipe:
    kind: str = "splash"
    seed: int = 42
    size: int = 512
    canvas_mm: float = 240.0
    volume_ml: float = 1.2
    speed_m_s: float = 4.0
    viscosity_mpas: float = 4.0
    surface_tension_mnm: float = 55.0
    density_kg_m3: float = 1060.0
    surface_roughness: float = 0.45
    contact_angle_deg: float = 12.0
    angle_deg: float = 15.0
    direction_deg: float = 0.0
    drag_length_mm: float = 150.0
    drag_width_mm: float = 42.0
    drag_curve: float = 0.18
    absorption_mm: float = 0.025
    wet_roughness: float = 0.22
    dry_roughness: float = 0.65
    deep_rgb: tuple = (65, 3, 7)
    thin_rgb: tuple = (125, 13, 19)
    parcels: int = 12000
    fine_splatter: float = 0.0
    splatter_length_mm: float = 6.0
    splatter_spread_mm: float = 12.0

    def validate(self):
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        for name, low, high in (("seed", 0, 2**32 - 1), ("size", 64, 2048), ("parcels", 1000, 100000)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in [{low}, {high}]")
        limits = {
            "canvas_mm": (10, 2000), "volume_ml": (0.001, 100), "speed_m_s": (0.01, 15),
            "viscosity_mpas": (0.5, 100), "surface_tension_mnm": (10, 150),
            "density_kg_m3": (500, 2000), "surface_roughness": (0, 1),
            "contact_angle_deg": (2, 80), "angle_deg": (0, 75), "direction_deg": (-360, 360),
            "drag_length_mm": (1, 1500), "drag_width_mm": (1, 500), "drag_curve": (-0.5, 0.5),
            "absorption_mm": (0.001, 1), "wet_roughness": (0, 1), "dry_roughness": (0, 1),
            "fine_splatter": (0, 1), "splatter_length_mm": (0, 30), "splatter_spread_mm": (0, 60),
        }
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
        for name in ("deep_rgb", "thin_rgb"):
            value = getattr(self, name)
            if not isinstance(value, (tuple, list)) or len(value) != 3 or any(type(x) is not int or not 0 <= x <= 255 for x in value):
                raise ValueError(f"{name} must contain three integer sRGB values in [0, 255]")
        return self


def preset(kind):
    changes = {
        "splash": {},
        "smear": {"volume_ml": 2.8, "speed_m_s": 2.0, "canvas_mm": 240.0},
        "pool": {"volume_ml": 3.0, "speed_m_s": 0.35, "canvas_mm": 180.0, "angle_deg": 0.0},
        "drops": {"volume_ml": 0.24, "speed_m_s": 1.8, "canvas_mm": 110.0, "angle_deg": 25.0},
    }
    return replace(Recipe(), kind=kind, **changes[kind])


def impact_scales(volume_ml, speed, recipe):
    """SI quantities. Empirical inertial/capillary and viscous spread limits.

    beta ~ We**1/4 (Clanet et al., 2004); the Re**1/5 cap and constants
    here are an art model, not a calibrated blood-impact predictor.
    """
    diameter = (6 * volume_ml * 1e-6 / math.pi) ** (1 / 3)
    rho = recipe.density_kg_m3
    sigma = recipe.surface_tension_mnm * 0.001
    mu = recipe.viscosity_mpas * 0.001
    weber = rho * speed**2 * diameter / sigma
    reynolds = rho * speed * diameter / mu
    beta = max(1.0, min(max(weber, 1)**0.25, max(reynolds, 1)**0.2))
    radius = diameter * 0.5
    capillary_time = math.sqrt(rho * radius**3 / sigma)
    return radius, beta * radius, capillary_time, weber, reynolds


class Surface:
    """Raster stores volume in mm^3 per texel, not arbitrary stamp opacity."""

    def __init__(self, recipe, cancelled=None, impact_steps=80):
        self.recipe = recipe.validate()
        self.cancelled = cancelled
        if type(impact_steps) is not int or not 16 <= impact_steps <= 160:
            raise ValueError("impact_steps must be an integer between 16 and 160")
        self.impact_steps = impact_steps
        self.rng = np.random.default_rng(recipe.seed)
        self.volume = np.zeros((recipe.size, recipe.size), dtype=np.float64)
        self.mm_per_pixel = recipe.canvas_mm / recipe.size
        # The substrate is a spatially correlated, fixed random field, in mm.
        # A fixed source grid makes roughness independent of export resolution.
        coarse = self.rng.normal(size=(192, 192))
        coarse = gaussian_filter(coarse, max(0.6, 0.8 * 192 / recipe.canvas_mm), mode="reflect")
        coarse /= max(float(coarse.std()), 1e-8)
        self.grain = coarse
        self.escaped_mm3 = 0.0
        self.carried_mm3 = 0.0
        self.fine_splatter_mm3 = 0.0
        self.fine_fragment_count = 0

    def check_cancelled(self):
        if self.cancelled is not None and self.cancelled():
            raise InterruptedError("Generation superseded by a newer preview")

    def roughness_at(self, x, y):
        scale = self.grain.shape[0] / self.recipe.canvas_mm
        return map_coordinates(self.grain, [y * scale + 95.5, x * scale + 95.5], order=1, mode="nearest")

    def deposit(self, x, y, volume):
        """Bilinear particle-to-grid transfer; out-of-canvas volume is counted."""
        px = np.asarray(x) / self.mm_per_pixel + (self.recipe.size - 1) / 2
        py = np.asarray(y) / self.mm_per_pixel + (self.recipe.size - 1) / 2
        px, py, volume = np.broadcast_arrays(px, py, np.asarray(volume))
        ix, iy = np.floor(px).astype(int), np.floor(py).astype(int)
        fx, fy = px - ix, py - iy
        for dx, dy, weight in ((0, 0, (1-fx)*(1-fy)), (1, 0, fx*(1-fy)),
                               (0, 1, (1-fx)*fy), (1, 1, fx*fy)):
            xx, yy = ix + dx, iy + dy
            amount = volume * weight
            valid = (xx >= 0) & (xx < self.recipe.size) & (yy >= 0) & (yy < self.recipe.size)
            np.add.at(self.volume, (yy[valid], xx[valid]), amount[valid])
            self.escaped_mm3 += float(amount[~valid].sum())

    def impact(self, center, volume_ml, speed, *, direction=None, oblique=None, detail=1.0):
        self.check_cancelled()
        r = self.recipe
        radius, spread, tau, weber, _ = impact_scales(volume_ml, speed, r)
        radius *= 1000
        spread *= 1000
        n = max(600, int(r.parcels * volume_ml / r.volume_ml))
        previous = self.volume
        self.volume = np.zeros_like(previous)
        theta = self.rng.uniform(0, math.tau, n)
        # Correlated perturbations seed uneven rim expansion. Surface friction
        # then changes trajectories locally; this is not noise cut into alpha.
        rim = gaussian_filter1d(self.rng.normal(size=48), 1.2, mode="wrap")
        rim /= max(float(rim.std()), 1e-8)
        rim = np.clip(1 + rim * (0.10 + r.surface_roughness * 0.13) * detail, 0.45, 1.7)
        modulation = np.interp(theta / math.tau * 48, np.arange(49), np.r_[rim, rim[0]])
        # A few unstable rim sectors become thin ligaments at high energy.
        instability = float(np.clip((math.sqrt(weber) - 12) / 65, 0, 1)) * detail
        for _ in range(10):
            bearing = self.rng.uniform(0, math.tau)
            delta = (theta - bearing + math.pi) % math.tau - math.pi
            width = self.rng.uniform(0.018, 0.055)
            modulation += instability * self.rng.uniform(0.5, 1.8) * np.exp(-0.5 * (delta / width)**2)
        runout = spread * np.sqrt(self.rng.random(n)) * modulation
        start = radius * 0.18 * np.sqrt(self.rng.random(n))
        x = np.cos(theta) * start
        y = np.sin(theta) * start
        vx = np.cos(theta) * runout / tau
        vy = np.sin(theta) * runout / tau
        incidence = math.radians(r.angle_deg if oblique is None else oblique)
        vx = vx * (1 + 0.55 * math.sin(incidence)) + spread / tau * math.sin(incidence) * 0.35
        vy *= 1 - 0.25 * math.sin(incidence)
        angle = math.radians(r.direction_deg if direction is None else direction)
        co, si = math.cos(angle), math.sin(angle)
        vx, vy = co * vx - si * vy, si * vx + co * vy
        x, y = co * x - si * y + center[0], si * x + co * y + center[1]
        # No parcel starts faster than the incoming liquid. The model dissipates
        # kinetic energy through substrate drag, with no added external force.
        limit = np.minimum(1, speed * 1000 / np.maximum(np.hypot(vx, vy), 1e-9))
        vx *= limit
        vy *= limit
        remaining = np.full(n, volume_ml * 1000 / n)
        dt = tau / 16 * (80 / self.impact_steps)
        for step in range(self.impact_steps):
            if step % 4 == 0:
                self.check_cancelled()
            grain = self.roughness_at(x, y)
            friction = np.clip(1 + r.surface_roughness * 0.5 * grain, 0.35, 2.8)
            damping = np.exp(-dt / tau * friction)
            # Exact position increment for locally constant linear drag.
            advance = tau / friction * (1 - damping)
            x += vx * advance
            y += vy * advance
            vx *= damping
            vy *= damping
            adhesion = 1 - np.exp(-dt / tau * (0.40 + r.surface_roughness * 0.22) * friction)
            adhesion *= 1 - math.exp(-step * (80 / self.impact_steps) / 12)
            deposited = remaining * adhesion
            self.deposit(x, y, deposited)
            remaining -= deposited
        self.deposit(x, y, remaining)
        # A parcel represents a small fluid footprint, rather than an infinitely
        # narrow ray. Low-energy drops have a smoother rim than broken sheets.
        footprint_mm = max(0.12, spread * (0.045 - 0.025 * instability))
        self.volume = previous + gaussian_filter(self.volume, max(0.6, footprint_mm / self.mm_per_pixel), mode="reflect")

    def splash(self):
        r = self.recipe
        _, spread, _, weber, _ = impact_scales(r.volume_ml, r.speed_m_s, r)
        # Fragment count/fraction are controlled approximations to sheet breakup.
        breakup = np.clip((math.sqrt(weber) - 5) / 100, 0, 1)
        fraction = float(breakup * (0.08 + 0.12 * r.surface_roughness))
        film = r.volume_ml * (1 - fraction)
        weights = np.r_[0.60, self.rng.dirichlet(np.ones(5)) * 0.40]
        for i, weight in enumerate(weights):
            center = np.zeros(2) if i == 0 else self.rng.normal(0, spread * 1000 * 0.30, 2)
            self.impact(center, film * weight, r.speed_m_s * (1 if i == 0 else 0.75))
        if fraction <= 0:
            return
        count = int(18 + 80 * breakup * (0.4 + r.surface_roughness))
        amounts = self.rng.lognormal(0, 1.0, count)
        amounts *= r.volume_ml * fraction / amounts.sum()
        heading = math.radians(r.direction_deg)
        for amount in amounts:
            theta = self.rng.uniform(0, math.tau)
            elevation = self.rng.uniform(0.25, 1.1)
            launch = r.speed_m_s * self.rng.uniform(0.045, 0.22)
            horizontal = launch * math.cos(elevation)
            vertical = launch * math.sin(elevation)
            vx = horizontal * math.cos(theta) + r.speed_m_s * math.sin(math.radians(r.angle_deg)) * 0.12
            vy = horizontal * math.sin(theta)
            flight = 2 * vertical / 9.81
            offset = spread * 0.45
            x, y = (vx * flight + offset * math.cos(theta)) * 1000, (vy * flight + offset * math.sin(theta)) * 1000
            center = (x * math.cos(heading) - y * math.sin(heading), x * math.sin(heading) + y * math.cos(heading))
            self.impact(center, float(amount), max(0.05, vertical),
                        direction=math.degrees(theta) + r.direction_deg, oblique=35, detail=0.4)

    def pool(self):
        r = self.recipe
        # Settled-puddle approximation: capillary length and contact angle set
        # a characteristic depth; volume sets area. Pinning perturbs the contact
        # line. This is an equilibrium construction, not a time-dependent solve.
        capillary_mm = 1000 * math.sqrt(r.surface_tension_mnm * 0.001 / (r.density_kg_m3 * 9.81))
        depth = 2 * capillary_mm * math.sin(math.radians(r.contact_angle_deg) / 2)
        radius = math.sqrt(r.volume_ml * 1000 / (math.pi * depth))
        # Construct on a larger physical domain so clipped volume can be counted.
        extent = max(r.canvas_mm, radius * 3.8)
        count = int(math.ceil(extent / self.mm_per_pixel))
        if count > 4096:
            raise ValueError("Pool is much larger than the canvas; increase canvas_mm or contact_angle_deg")
        yy, xx = np.indices((count, count), dtype=float)
        self.check_cancelled()
        xx = (xx - (count - 1) / 2) * self.mm_per_pixel
        yy = (yy - (count - 1) / 2) * self.mm_per_pixel
        theta = np.arctan2(yy, xx) - math.radians(r.direction_deg)
        rim = gaussian_filter1d(self.rng.normal(size=32), 1.2, mode="wrap")
        rim /= max(float(rim.std()), 1e-8)
        boundary = radius * np.clip(1 + np.interp(theta % math.tau / math.tau * 32, np.arange(33), np.r_[rim, rim[0]]) * (0.10 + r.surface_roughness * 0.18), 0.55, 1.55)
        substrate = self.roughness_at(xx, yy)
        edge_distance = boundary - np.hypot(xx, yy) - r.surface_roughness * capillary_mm * 1.4 * substrate
        profile = np.clip(edge_distance / (capillary_mm * 1.5), 0, 1)
        profile = np.maximum(0, profile - r.surface_roughness * 0.07 * substrate)
        profile[edge_distance <= 0] = 0
        amounts = profile / profile.sum() * r.volume_ml * 1000
        self.check_cancelled()
        self.deposit(xx.ravel(), yy.ravel(), amounts.ravel())

    def drops(self):
        r = self.recipe
        amounts = self.rng.dirichlet(np.full(9, 1.3)) * r.volume_ml
        angle = math.radians(r.direction_deg)
        for index, amount in enumerate(amounts):
            x = (index / 8 - 0.5) * r.canvas_mm * 0.58
            y = self.rng.normal(0, r.canvas_mm * 0.075)
            center = (x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle))
            self.impact(center, float(amount), r.speed_m_s, detail=0.6)

    def smear(self):
        r = self.recipe
        # Uneven contact channels represent a blood-covered fabric/body contact.
        # Each channel has a finite reservoir, friction and a release history.
        n = max(180, r.parcels // 24)
        lane = self.rng.uniform(-1, 1, n)
        channels = gaussian_filter1d(self.rng.uniform(0.1, 1.0, 25), 0.7)
        contact = np.interp(lane, np.linspace(-1, 1, len(channels)), channels)**2
        load = (1 - lane**2)**0.65 * self.rng.lognormal(0, 0.4, n) * contact
        remaining = load / load.sum() * r.volume_ml * 1000
        lag = np.interp(lane, np.linspace(-1, 1, 14), self.rng.uniform(-0.12, 0.12, 14))
        lag += self.rng.uniform(-0.015, 0.015, n)
        phase = self.rng.uniform(0, math.tau, n)
        lift_at = np.interp(lane, np.linspace(-1, 1, 18), self.rng.uniform(0.4, 1.1, 18))
        release_rate = (2.6 / r.drag_length_mm) * (4 / r.viscosity_mpas)**0.25
        release_rate *= (2 / r.speed_m_s)**0.15
        steps = max(200, int(r.drag_length_mm / self.mm_per_pixel * 2))
        step_mm = r.drag_length_mm / steps
        angle = math.radians(r.direction_deg)
        co, si = math.cos(angle), math.sin(angle)
        for step in range(steps):
            if step % 8 == 0:
                self.check_cancelled()
            t = (step + 0.5) / steps
            s = t + lag
            center_x = (s - 0.5) * r.drag_length_mm
            center_y = r.drag_curve * r.drag_length_mm * np.sin(math.pi * s)
            slope = r.drag_curve * math.pi * np.cos(math.pi * s)
            norm = np.sqrt(1 + slope**2)
            width = r.drag_width_mm * (0.95 - 0.43 * t)
            lateral = lane * width * 0.5 + np.sin(t * 6 + phase) * width * 0.018
            x = center_x - lateral * slope / norm
            y = center_y + lateral / norm
            x, y = x * co - y * si, x * si + y * co
            friction = np.clip(1 + r.surface_roughness * self.roughness_at(x, y) * 0.65, 0.12, 2.8)
            pressure = np.clip((lift_at - t) * 6, 0, 1)
            amount = remaining * (1 - np.exp(-release_rate * step_mm * friction * pressure))
            self.deposit(x, y, amount)
            remaining -= amount
        self.carried_mm3 = float(remaining.sum())

    def add_fine_splatter(self):
        """Break off a small volume into fine rim streaks and satellite drops.

        This art-directed secondary stage leaves the original trajectory field
        intact. A separate random stream keeps the body and fragment directions
        stable as the fine-splatter controls change.
        """
        r = self.recipe
        count = int(round(r.fine_splatter * 320))
        if count == 0 or self.volume.sum() <= 0:
            return
        self.check_cancelled()
        height = gaussian_filter(self.volume, 0.7) / self.mm_per_pixel**2
        components, _ = label(height > max(float(height.max()) * 0.008, 0.001))
        masses = np.bincount(components.ravel(), weights=self.volume.ravel())
        masses[0] = 0
        if masses.max() <= 0:
            return
        # Follow the large deposits, rather than adding another halo around
        # every existing speck. Only the outside of each body seeds fragments.
        body = binary_fill_holes(masses[components] >= masses.max() * 0.03)
        edge_y, edge_x = np.nonzero(body & ~binary_erosion(body))
        if len(edge_x) == 0:
            return
        grad_y, grad_x = np.gradient(gaussian_filter(body.astype(float), 1.0))
        rng = np.random.default_rng(np.random.SeedSequence([r.seed, 0xF17E]))
        # Always sample the full candidate set so increasing Amount reveals
        # additional fragments along the same directions, not a new pattern.
        choices = rng.integers(0, len(edge_x), 320)
        y, x = edge_y[choices], edge_x[choices]
        nx, ny = -grad_x[y, x], -grad_y[y, x]
        norm = np.hypot(nx, ny)
        fallback_x, fallback_y = x - edge_x.mean(), y - edge_y.mean()
        nx = np.where(norm > 1e-8, nx, fallback_x)
        ny = np.where(norm > 1e-8, ny, fallback_y)
        norm = np.maximum(np.hypot(nx, ny), 1e-8)
        nx, ny = nx / norm, ny / norm
        angle = rng.uniform(-0.40, 0.40, 320)
        nx, ny = nx * np.cos(angle) - ny * np.sin(angle), nx * np.sin(angle) + ny * np.cos(angle)
        gap = r.splatter_spread_mm * rng.random(320)**2
        gap[rng.random(320) < 0.28] = 0
        length = r.splatter_length_mm * (0.12 + 0.88 * rng.random(320)**2)
        length *= (4 / r.viscosity_mpas)**0.25
        length[rng.random(320) < 0.35] = 0
        bend = rng.uniform(-0.14, 0.14, 320) * r.surface_roughness
        weights = rng.lognormal(0, 0.7, 320)[:count]
        volume = float(self.volume.sum()) * 0.04 * r.fine_splatter
        amounts = weights / weights.sum() * volume
        self.fine_splatter_mm3 = volume
        self.fine_fragment_count = count
        # The fine layer borrows at most 4% of the deposited liquid. This keeps
        # the center's silhouette fixed and preserves the total volume budget.
        base = self.volume * (1 - 0.04 * r.fine_splatter)
        layers = [[], [], []]
        widths = (0.16, 0.32, 0.64)
        for i in range(count):
            if i % 32 == 0:
                self.check_cancelled()
            start_x = (x[i] - (r.size - 1) / 2) * self.mm_per_pixel + nx[i] * gap[i]
            start_y = (y[i] - (r.size - 1) / 2) * self.mm_per_pixel + ny[i] * gap[i]
            if length[i] == 0:
                travel, curve, portions = np.zeros(1), np.zeros(1), np.ones(1)
            else:
                samples = min(1024, max(24, int(length[i] / self.mm_per_pixel * 3)))
                phase = np.linspace(0, 4, samples)
                # Exponentially slowing fragments shed a finite reservoir.
                # Faster mass loss than slowing produces a thin, tapered tail.
                travel = (1 - np.exp(-phase)) / (1 - math.exp(-4))
                curve = bend[i] * length[i] * travel * (1 - travel)
                portions = np.exp(-1.6 * phase)
                portions /= portions.sum()
                travel *= length[i]
            xx = start_x + nx[i] * travel - ny[i] * curve
            yy = start_y + ny[i] * travel + nx[i] * curve
            footprint = np.cbrt(amounts[i]) * 0.4
            group = int(np.searchsorted((0.24, 0.48), footprint))
            layers[group].append((xx, yy, amounts[i] * portions))
        for width, fragments in zip(widths, layers):
            if not fragments:
                continue
            self.check_cancelled()
            self.volume = np.zeros_like(base)
            self.deposit(*(np.concatenate([fragment[axis] for fragment in fragments]) for axis in range(3)))
            base += gaussian_filter(self.volume, max(0.38, width / self.mm_per_pixel), mode="reflect")
        self.volume = base

    def generate(self):
        self.check_cancelled()
        getattr(self, self.recipe.kind)()
        self.check_cancelled()
        # Finite footprint of the deposited parcels, in physical units. Reflect
        # preserves raster mass; edge contamination is reported, never hidden.
        sigma = max(0.55, 0.22 / self.mm_per_pixel)
        self.volume = gaussian_filter(self.volume, sigma, mode="reflect")
        self.add_fine_splatter()
        height = self.volume / self.mm_per_pixel**2
        edge_mm3 = float(self.volume[[0, -1], :].sum() + self.volume[1:-1, [0, -1]].sum())
        stats = {
            "input_ml": self.recipe.volume_ml,
            "deposited_ml": float(self.volume.sum() / 1000),
            "outside_canvas_ml": self.escaped_mm3 / 1000,
            "carried_away_ml": self.carried_mm3 / 1000,
            "edge_ml": edge_mm3 / 1000,
            "max_thickness_mm": float(height.max()),
            "fine_splatter_ml": self.fine_splatter_mm3 / 1000,
            "fine_fragment_count": self.fine_fragment_count,
        }
        stats["balance_error_ml"] = stats["input_ml"] - sum(stats[k] for k in ("deposited_ml", "outside_canvas_ml", "carried_away_ml"))
        return height, stats


def material_maps(height, recipe):
    """Neutral maps: no painted light, shadows, environment or receiver texture."""
    depth = np.maximum(height, 0)
    optical = depth / recipe.absorption_mm
    alpha = 1 - np.exp(-optical)
    density = 1 - np.exp(-optical * 0.32)
    deep = np.asarray(recipe.deep_rgb, dtype=float)
    thin = np.asarray(recipe.thin_rgb, dtype=float)
    color = thin + (deep - thin) * density[..., None]
    rgba = np.dstack((color, alpha * 255)).round().clip(0, 255).astype(np.uint8)
    roughness = recipe.dry_roughness + (recipe.wet_roughness - recipe.dry_roughness) * density
    roughness = np.where(alpha > 0.01, roughness, 1)
    # Tangent normal convention: +X right, +Y up, +Z out. PNG rows point down.
    dy, dx = np.gradient(gaussian_filter(depth, 0.65), recipe.canvas_mm / recipe.size)
    normal = np.stack((-dx, dy, np.ones_like(depth)), axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    return {
        "color.png": Image.fromarray(rgba),
        "opacity.png": Image.fromarray(np.round(alpha * 255).astype(np.uint8)),
        "roughness.png": Image.fromarray(np.round(roughness * 255).astype(np.uint8)),
        "normal.png": Image.fromarray(np.round((normal * 0.5 + 0.5) * 255).astype(np.uint8)),
    }


def preview(rgba, dark=False):
    size = rgba.width
    yy, xx = np.indices((size, size))
    base = 62 if dark else 184
    checker = ((xx // max(8, size // 16) + yy // max(8, size // 16)) % 2) * 9
    background = np.repeat((base + checker)[..., None], 3, axis=2).astype(np.uint8)
    result = Image.fromarray(background).convert("RGBA")
    result.alpha_composite(rgba)
    return result.convert("RGB")


def export(directory, recipe, height, stats):
    directory.mkdir(parents=True, exist_ok=True)
    maps = material_maps(height, recipe)
    for name, image in maps.items():
        image.save(directory / name)
    maximum = max(float(height.max()), 1e-9)
    height16 = np.round(height / maximum * 65535).clip(0, 65535).astype(np.uint16)
    Image.fromarray(height16).save(directory / "thickness.png")
    # Raw float data is useful for inspection; thickness.png is the editable master.
    np.save(directory / "thickness_mm.npy", height.astype(np.float32))
    preview(maps["color.png"]).save(directory / "preview_light.png")
    preview(maps["color.png"], dark=True).save(directory / "preview_dark.png")
    (directory / "recipe.json").write_text(json.dumps(asdict(recipe), indent=2) + "\n", encoding="utf-8")
    metadata = {
        "model_version": MODEL_VERSION,
        "thickness_white_mm": maximum,
        "normal_convention": "+X right, +Y up, +Z out; linear RGB; not Frostbite channel packing",
        "color_space": "color.png = sRGB; opacity/roughness/normal/thickness = linear data",
        "statistics": stats,
    }
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return maps["color.png"]


def contact_sheet(items, path):
    tile, label, gap = 256, 30, 12
    columns = min(3, len(items))
    rows = math.ceil(len(items) / columns)
    sheet = Image.new("RGB", (columns * (tile * 2 + gap) + gap, rows * (tile + label + gap) + gap), (27, 29, 33))
    draw = ImageDraw.Draw(sheet)
    for index, (name, rgba) in enumerate(items):
        x, y = gap + (index % columns) * (tile * 2 + gap), gap + (index // columns) * (tile + label + gap)
        draw.text((x, y + 6), name + "   |   light / dark", fill=(235, 235, 235))
        for side in (0, 1):
            thumb = preview(rgba, dark=bool(side)).resize((tile, tile), Image.Resampling.LANCZOS)
            sheet.paste(thumb, (x + side * tile, y + label))
    sheet.save(path)


def load_recipe(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("recipe must be a JSON object")
    unknown = set(raw) - {f.name for f in fields(Recipe)}
    if unknown:
        raise ValueError(f"Unknown recipe parameters: {', '.join(sorted(unknown))}")
    kind = raw.get("kind", "splash")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    return replace(preset(kind), **raw).validate()


def rebake(source, output, overrides):
    allowed = {"absorption_mm", "wet_roughness", "dry_roughness", "deep_rgb", "thin_rgb"}
    if set(overrides) - allowed:
        raise ValueError("--rebake accepts only material settings: " + ", ".join(sorted(allowed)))
    recipe = replace(load_recipe(source / "recipe.json"), **overrides).validate()
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    scale = metadata.get("thickness_white_mm")
    if metadata.get("model_version") != MODEL_VERSION or type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid or incompatible thickness metadata")
    with Image.open(source / "thickness.png") as image:
        if image.size != (recipe.size, recipe.size) or image.mode not in ("I", "I;16", "I;16L"):
            raise ValueError("Edited thickness.png must remain a 16-bit grayscale image at the recipe resolution")
        values = np.asarray(image, dtype=np.float64)
    if values.min() < 0 or values.max() > 65535:
        raise ValueError("Thickness pixels must be in the 16-bit unsigned range")
    height = values / 65535 * scale
    stats = {"source": "edited thickness.png; not a new simulation", "deposited_ml": float(height.sum() * (recipe.canvas_mm / recipe.size)**2 / 1000)}
    export(output, recipe, height, stats)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=(*KINDS, "all"), help="Default: all, or the kind in --config")
    parser.add_argument("--config", type=Path, help="JSON recipe; generated recipe.json can be reused unchanged")
    parser.add_argument("--seed", type=int, help="Repeatable random seed (default 42)")
    parser.add_argument("--size", type=int, help="Square texture resolution, 64..2048 (default 512)")
    parser.add_argument("--count", type=int, default=3, help="Variants per kind, consecutive seeds (default 3)")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=JSON", help="Override a recipe field, e.g. viscosity_mpas=12")
    parser.add_argument("--output", type=Path, help="Default: build/decal_lab; existing outputs require --overwrite")
    parser.add_argument("--rebake", type=Path, help="Read edited thickness.png + recipe/metadata from this variant directory")
    parser.add_argument("--overwrite", action="store_true", help="Replace generated files at the selected destination")
    args = parser.parse_args(argv)
    try:
        overrides = {}
        valid = {f.name for f in fields(Recipe)}
        for setting in args.set:
            name, separator, value = setting.partition("=")
            if not separator or name not in valid:
                raise ValueError(f"Unknown or invalid setting: {setting}")
            if name == "kind":
                raise ValueError("Select the kind with --kind, not --set kind")
            overrides[name] = json.loads(value)
        if args.seed is not None:
            overrides["seed"] = args.seed
        if args.size is not None:
            overrides["size"] = args.size
        if not 1 <= args.count <= 30:
            raise ValueError("count must be between 1 and 30")
        if args.rebake:
            if args.config or args.kind:
                raise ValueError("--rebake reads its own recipe; do not combine it with --config or --kind")
            output = args.output or args.rebake.with_name(args.rebake.name + "_edited")
            if output.exists() and not args.overwrite:
                raise ValueError(f"Output exists: {output}. Choose a new --output or use --overwrite.")
            result = rebake(args.rebake, output, overrides)
            print(f"Rebuilt edited material maps: {result}")
            return 0
        base = load_recipe(args.config) if args.config else None
        kind = args.kind or (base.kind if base else "all")
        if base and kind == "all":
            raise ValueError("A recipe describes one kind; omit --kind all when using --config")
        recipes = []
        for chosen in KINDS if kind == "all" else (kind,):
            initial = replace(base or preset(chosen), **(overrides | {"kind": chosen})).validate()
            for index in range(args.count):
                recipes.append(replace(initial, seed=initial.seed + index).validate())
        output = args.output or ROOT / "build/decal_lab"
        targets = [output / f"{r.kind}_{r.seed}" for r in recipes]
        if not args.overwrite and any(p.exists() for p in [*targets, output / "contact_sheet.png"]):
            raise ValueError(f"Generated output already exists in {output}. Choose a new --output or use --overwrite.")
        output.mkdir(parents=True, exist_ok=True)
        items = []
        for recipe, target in zip(recipes, targets):
            print(f"Generating {target.name}...", flush=True)
            height, stats = Surface(recipe).generate()
            rgba = export(target, recipe, height, stats)
            items.append((target.name, rgba))
            print(f"  deposited={stats['deposited_ml']:.4f} ml, carried={stats['carried_away_ml']:.4f} ml, outside={stats['outside_canvas_ml']:.4f} ml", flush=True)
            if stats["outside_canvas_ml"] > recipe.volume_ml * 0.001 or stats["edge_ml"] > recipe.volume_ml * 0.0001:
                print("  Canvas clips this result: increase canvas_mm for a clean decal border.", flush=True)
        contact_sheet(items, output / "contact_sheet.png")
        print(f"Preview: {output / 'contact_sheet.png'}")
        return 0
    except (ValueError, TypeError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
