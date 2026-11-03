"""Latest-request-only preview worker, independent of the desktop UI toolkit."""

from dataclasses import asdict, dataclass
from pathlib import Path
import tempfile
import threading
import time

if __package__:
    from . import generate_decals as lab
else:
    import generate_decals as lab


MATERIAL_FIELDS = frozenset(("deep_rgb", "thin_rgb", "absorption_mm", "wet_roughness", "dry_roughness"))


def geometry_key(recipe):
    return tuple((name, value) for name, value in asdict(recipe).items() if name not in MATERIAL_FIELDS)


@dataclass
class Result:
    revision: int
    recipe: lab.Recipe
    height: object
    stats: dict
    maps: dict
    seconds: float
    reused_shape: bool
    draft: bool = False


class LatestRenderer:
    """One active job, one replaceable pending job, one cached thickness field.

    The callback runs on the worker thread. A GUI must marshal it onto its own
    event loop. Material changes do not interrupt an identical shape calculation.
    """

    def __init__(self, callback, simulate=None):
        self.callback = callback
        self.simulate = simulate
        self.condition = threading.Condition()
        self.revision = 0
        self.pending = None
        self.active_key = None
        self.cancel = threading.Event()
        self.stopped = False
        self.cache = None
        self.thread = threading.Thread(target=self._run, name="decal-preview", daemon=True)
        self.thread.start()

    def request(self, recipe, draft=False):
        recipe.validate()
        with self.condition:
            self.revision += 1
            self.pending = (self.revision, recipe, draft)
            if self.active_key != (geometry_key(recipe), draft):
                self.cancel.set()
            self.condition.notify()
            return self.revision

    def invalidate(self, recipe=None, draft=False):
        """Immediately retire the old preview while a slider's debounce runs."""
        with self.condition:
            self.revision += 1
            self.pending = None
            if recipe is None or self.active_key != (geometry_key(recipe), draft):
                self.cancel.set()
            return self.revision

    def close(self):
        with self.condition:
            self.stopped = True
            self.cancel.set()
            self.pending = None
            self.condition.notify()
        self.thread.join(timeout=5)

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or self.pending is not None)
                if self.stopped:
                    return
                revision, recipe, draft = self.pending
                self.pending = None
                key = (geometry_key(recipe), draft)
                self.active_key = key
                self.cancel = threading.Event()
                cancelled = self.cancel
            started = time.perf_counter()
            try:
                reused = self.cache is not None and self.cache[0] == key
                if reused:
                    _, height, stats = self.cache
                else:
                    if self.simulate is not None:
                        height, stats = self.simulate(recipe, cancelled.is_set)
                    else:
                        height, stats = lab.Surface(recipe, cancelled=cancelled.is_set, impact_steps=24 if draft else 80).generate()
                    if cancelled.is_set():
                        continue
                    self.cache = (key, height, stats)
                maps = lab.material_maps(height, recipe)
                result = Result(revision, recipe, height, stats, maps, time.perf_counter() - started, reused, draft)
                error = None
            except InterruptedError:
                continue
            except Exception as exception:
                result, error = None, str(exception)
            with self.condition:
                current = not self.stopped and revision == self.revision
            if current:
                self.callback(revision, result, error)


def export_variant(recipe, parent, cached=None):
    """Write a new complete variant directory, never replace existing artwork."""
    recipe.validate()
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    if cached is not None and not cached.draft and geometry_key(cached.recipe) == geometry_key(recipe):
        height, stats = cached.height, cached.stats
    else:
        height, stats = lab.Surface(recipe).generate()
    stem = f"{recipe.kind}_{recipe.seed}_{time.strftime('%Y%m%d_%H%M%S')}"
    target = parent / stem
    suffix = 1
    while target.exists():
        target = parent / f"{stem}_{suffix}"
        suffix += 1
    with tempfile.TemporaryDirectory(prefix=".decal-export-", dir=parent) as temporary:
        lab.export(Path(temporary), recipe, height, stats)
        Path(temporary).rename(target)
    return target
