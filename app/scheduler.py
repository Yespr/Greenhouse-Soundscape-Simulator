from datetime import datetime, time
import logging
import random
from threading import Event, Lock, Thread

from app.audio_engine import AudioEngine
from app.models import EngineState, SoundEntry, SoundProfile, SoundscapeMode


DAY_START = time(hour=7)
EVENING_START = time(hour=18)
MIN_RANDOM_DELAY_SECONDS = 0.1

logger = logging.getLogger(__name__)


class SoundscapeScheduler:
    def __init__(self, audio_engine: AudioEngine) -> None:
        self._audio_engine = audio_engine
        self._mode = SoundscapeMode.off
        self._active_profile: SoundProfile | None = None
        self._lock = Lock()
        self._random_playback_lock = Lock()
        self._random_stop = Event()
        self._random_workers: dict[int, Thread] = {}

    @property
    def mode(self) -> SoundscapeMode:
        return self._mode

    def state(self) -> EngineState:
        return EngineState(
            running=self._audio_engine.running,
            mode=self._mode,
            active_profile=self._active_profile,
        )

    def set_mode(self, mode: SoundscapeMode, sounds: list[SoundEntry]) -> EngineState:
        self._mode = mode
        if mode == SoundscapeMode.off:
            self.stop()
            return self.state()
        if mode == SoundscapeMode.day:
            return self.start(SoundProfile.day, sounds)
        if mode == SoundscapeMode.evening:
            return self.start(SoundProfile.evening, sounds)
        return self.start(self._auto_profile(), sounds)

    def start(self, profile: SoundProfile | None, sounds: list[SoundEntry]) -> EngineState:
        if profile is None:
            profile = self._active_profile or self._auto_profile()

        logger.info("scheduler start requested")
        logger.info("active mode=%s active_profile=%s", self._mode.value, profile.value)
        self._stop_random_workers()

        plan = self._audio_engine.start(profile, sounds)
        with self._lock:
            self._active_profile = profile

        for sound in plan.random_sounds:
            logger.info(
                "random sound discovered id=%s name=%s profile=%s min=%s max=%s probability=%s",
                sound.id,
                sound.name,
                sound.profile.value,
                sound.min_interval_seconds,
                sound.max_interval_seconds,
                sound.probability,
            )
            self._start_random_worker(sound)
        return self.state()

    def stop(self) -> EngineState:
        logger.info("scheduler stop requested")
        self._stop_random_workers()
        self._audio_engine.stop()
        with self._lock:
            self._active_profile = None
        return self.state()

    def refresh(self, sounds: list[SoundEntry]) -> EngineState:
        if self._mode == SoundscapeMode.off:
            return self.state()
        if self._mode == SoundscapeMode.auto:
            self._active_profile = self._auto_profile()
            return self.start(self._active_profile, sounds)
        return self.start(self._active_profile, sounds)

    def active_sound_report(self, sounds: list[SoundEntry]) -> dict[str, object]:
        effective_profile = self._effective_profile()
        with self._lock:
            worker_ids = set(self._random_workers.keys())

        items = []
        for sound in sounds:
            reasons = []
            included = True

            if self._mode == SoundscapeMode.off:
                included = False
                reasons.append("mode is off")

            if not sound.enabled:
                included = False
                reasons.append("sound is disabled")

            if effective_profile is None:
                included = False
                reasons.append("no active profile selected")
            elif sound.profile != effective_profile and sound.profile != SoundProfile.both:
                included = False
                reasons.append(f"profile {sound.profile.value} does not match active profile {effective_profile.value}")

            if included:
                reasons.append(f"included as {sound.type.value} sound")

            items.append(
                {
                    "id": sound.id,
                    "name": sound.name,
                    "file_path": sound.file_path,
                    "enabled": sound.enabled,
                    "profile": sound.profile.value,
                    "type": sound.type.value,
                    "repeat_count_min": sound.repeat_count_min,
                    "repeat_count_max": sound.repeat_count_max,
                    "repeat_gap_seconds": sound.repeat_gap_seconds,
                    "included": included,
                    "reasons": reasons,
                    "random_worker_active": sound.id in worker_ids,
                }
            )

        return {
            "running": self._audio_engine.running,
            "mode": self._mode.value,
            "active_profile": effective_profile.value if effective_profile else None,
            "sounds": items,
        }

    def _auto_profile(self) -> SoundProfile:
        now = datetime.now().time()
        if DAY_START <= now < EVENING_START:
            return SoundProfile.day
        return SoundProfile.evening

    def _effective_profile(self) -> SoundProfile | None:
        if self._mode == SoundscapeMode.off:
            return None
        if self._mode == SoundscapeMode.day:
            return SoundProfile.day
        if self._mode == SoundscapeMode.evening:
            return SoundProfile.evening
        if self._mode == SoundscapeMode.auto:
            return self._active_profile or self._auto_profile()
        return self._active_profile

    def _start_random_worker(self, sound: SoundEntry) -> None:
        worker = Thread(
            target=self._random_worker,
            args=(sound, self._random_stop),
            name=f"soundscape-random-{sound.id}",
            daemon=True,
        )
        with self._lock:
            self._random_workers[sound.id] = worker
        worker.start()

    def _stop_random_workers(self) -> None:
        self._random_stop.set()
        with self._lock:
            workers = list(self._random_workers.values())
            self._random_workers.clear()

        for worker in workers:
            worker.join(timeout=2)

        self._random_stop = Event()

    def _random_worker(self, sound: SoundEntry, stop_event: Event) -> None:
        while not stop_event.is_set():
            delay = random.uniform(sound.min_interval_seconds, sound.max_interval_seconds)
            logger.info("random delay selected id=%s name=%s delay=%.2f", sound.id, sound.name, delay)

            if stop_event.wait(max(delay, MIN_RANDOM_DELAY_SECONDS)):
                break

            logger.info("random timer fired id=%s name=%s", sound.id, sound.name)
            if self._should_play(sound.probability):
                try:
                    with self._random_playback_lock:
                        if stop_event.is_set():
                            break
                        played = self._play_random_burst(sound, stop_event)
                        if not played:
                            break
                    logger.info("random sound played id=%s name=%s", sound.id, sound.name)
                except Exception:
                    logger.exception("random sound failed id=%s name=%s", sound.id, sound.name)
            else:
                logger.info(
                    "random sound skipped id=%s name=%s probability=%s",
                    sound.id,
                    sound.name,
                    sound.probability,
                )

    def _should_play(self, probability: int) -> bool:
        if probability >= 100:
            return True
        if probability <= 0:
            return False
        return random.random() <= (probability / 100.0)

    def _play_random_burst(self, sound: SoundEntry, stop_event: Event) -> bool:
        repeat_count = random.randint(sound.repeat_count_min, sound.repeat_count_max)
        logger.info(
            "random repeat count selected id=%s name=%s repeat_count=%s",
            sound.id,
            sound.name,
            repeat_count,
        )

        for index in range(repeat_count):
            if stop_event.is_set():
                logger.info(
                    "random repeat interrupted before playback id=%s name=%s repeat_index=%s",
                    sound.id,
                    sound.name,
                    index + 1,
                )
                return False

            logger.info(
                "random repeated playback id=%s name=%s repeat_index=%s repeat_count=%s",
                sound.id,
                sound.name,
                index + 1,
                repeat_count,
            )
            self._audio_engine.play_once_and_wait(sound, stop_event)

            if index < repeat_count - 1:
                if stop_event.wait(sound.repeat_gap_seconds):
                    logger.info(
                        "random repeat interrupted during gap id=%s name=%s repeat_index=%s",
                        sound.id,
                        sound.name,
                        index + 1,
                    )
                    return False

        return True
