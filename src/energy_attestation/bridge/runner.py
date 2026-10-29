"""The bridge loop: meter counter in, gapless on chain attestations out.

How it stays honest:
  * Attestations always start at the project's on chain chain tip, so the
    record is gapless and nothing is ever double counted.
  * Energy = counter now minus counter at the last attestation. Missed hours
    (power cut, no internet) are folded into one longer attestation instead of
    being invented hour by hour.
  * Periods never extend past the current time.
  * A counter that goes backwards (inverter replaced or reset) is never
    attested; the bridge re-baselines and logs it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from ..errors import ContractRevertError, EnergySDKError
from ..sdk import EnergySDK
from ..types import AttestParams
from .sources import EnergySource, SourceError

log = logging.getLogger("energy_bridge")

HOUR = 3600


@dataclass
class BridgeState:
    project_id: int
    baseline_wh: Optional[int] = None  # counter value at the chain tip
    baseline_ts: Optional[int] = None  # unix time that baseline_wh refers to
    last_uid: str = ""
    last_tx: str = ""

    @classmethod
    def load(cls, path: str, project_id: int) -> "BridgeState":
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if int(data.get("project_id", project_id)) != int(project_id):
                raise EnergySDKError(f"state file {path} belongs to project {data['project_id']}, not {project_id}")
            return cls(**data)
        return cls(project_id=int(project_id))

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self), f, indent=2)
        os.replace(tmp, path)


@dataclass
class TickResult:
    action: str  # "baseline", "attested", "waiting", "reset", "dry-run"
    detail: str
    uid: str = ""
    tx_hash: str = ""
    energy_wh: int = 0
    from_ts: int = 0
    to_ts: int = 0


class Bridge:
    def __init__(
        self,
        sdk: EnergySDK,
        source: EnergySource,
        project_id: int,
        state_path: str,
        interval_hours: int = 1,
        metadata_uri: str = "",
        clock: Callable[[], float] = time.time,
        dry_run: bool = False,
    ):
        if interval_hours < 1:
            raise ValueError("interval_hours must be at least 1")
        self.sdk = sdk
        self.source = source
        self.project_id = int(project_id)
        self.state_path = state_path
        self.interval_s = int(interval_hours) * HOUR
        self.metadata_uri = metadata_uri
        self.clock = clock
        self.dry_run = dry_run
        self.state = BridgeState.load(state_path, self.project_id)

    def _save(self):
        if not self.dry_run:
            self.state.save(self.state_path)

    def tick(self) -> TickResult:
        now = int(self.clock())
        total_wh = self.source.read_total_wh()
        tip = self.sdk.read.get_project_last_timestamp(self.project_id)

        # First run: remember the counter. A new project starts at the next whole
        # hour, so no attested period ever begins before the device was observed.
        if self.state.baseline_wh is None:
            start = tip if tip > 0 else now + (-now) % HOUR
            self.state.baseline_wh, self.state.baseline_ts = total_wh, start
            self._save()
            return TickResult("baseline", f"baseline {total_wh} Wh, attesting from {start}")

        if tip > 0 and tip != self.state.baseline_ts:
            # Someone else extended the chain (a manual correction, another device).
            # The counter at the new tip is unknown, so re-baseline instead of guessing.
            self.state.baseline_wh, self.state.baseline_ts = total_wh, tip
            self._save()
            return TickResult("reset", f"chain tip moved to {tip} outside this bridge; re-baselined at {total_wh} Wh")

        start = tip if tip > 0 else int(self.state.baseline_ts)
        if tip > now:
            return TickResult("waiting", f"chain tip {tip} is ahead of the local clock {now}; check the system time")

        whole_periods = (now - start) // self.interval_s
        if whole_periods < 1:
            return TickResult("waiting", f"next attestation at {start + self.interval_s}")

        delta = total_wh - int(self.state.baseline_wh)
        if delta < 0:
            previous = self.state.baseline_wh
            self.state.baseline_wh = total_wh
            self._save()
            return TickResult("reset", f"counter went backwards ({total_wh} < {previous}); re-baselined, nothing attested")

        minutes = whole_periods * self.interval_s // 60
        params = AttestParams(
            project_id=self.project_id,
            readings=[delta],
            reading_interval_minutes=minutes,
            from_timestamp=start,
            method=self.source.method,
            metadata_uri=self.metadata_uri,
        )
        to_ts = start + minutes * 60
        if self.dry_run:
            return TickResult("dry-run", f"would attest {delta} Wh for {start}..{to_ts}", energy_wh=delta, from_ts=start, to_ts=to_ts)

        res = self.sdk.attestations.attest(params)
        self.state.baseline_wh, self.state.baseline_ts = total_wh, to_ts
        self.state.last_uid, self.state.last_tx = res.uid, res.tx_hash
        self._save()
        return TickResult("attested", f"{delta} Wh for {start}..{to_ts}", res.uid, res.tx_hash, delta, start, to_ts)

    def run_forever(self, poll_s: int = 300) -> None:
        log.info("bridge started for project %s (attester %s)", self.project_id, self.sdk.address)
        while True:
            try:
                r = self.tick()
                log.info("%s: %s %s", r.action, r.detail, r.uid)
            except (SourceError, EnergySDKError) as e:
                # A failed read or transaction is retried next poll; the chain stays gapless.
                log.warning("tick failed, will retry: %s", e)
                if isinstance(e, ContractRevertError):
                    log.warning("revert %s %s", e.error_name, e.error_args)
            except Exception as e:  # noqa: BLE001  never let the device loop die
                log.exception("unexpected error, will retry: %s", e)
            time.sleep(poll_s)
