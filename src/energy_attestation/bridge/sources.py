"""Energy sources: read a lifetime energy counter from a real meter or inverter.

Every source returns a cumulative energy counter in Wh. The bridge turns the
difference between two readings into an attestation, which is how meters work
and why it survives restarts, power cuts and missed hours.

Two kinds of source:
  * Counter sources read the inverter's own lifetime kWh register. Best option.
  * Power integration samples PV power every few seconds and adds it up, for
    inverters (like the Felicity IVEM series) that expose PV power but no
    lifetime energy register. Attested with method "iot-integrated" so anyone
    reading the chain can see how the number was produced.

Register maps differ between models and firmware. Always confirm with
`energy-bridge read` against the inverter's screen before attesting anything.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, replace
from typing import List, Optional, Protocol

log = logging.getLogger("energy_bridge")


class SourceError(RuntimeError):
    pass


class EnergySource(Protocol):
    method: str

    def read_total_wh(self) -> int:
        """Return the lifetime energy counter in Wh."""


def _combine(words, word_order: str, signed: bool = False) -> int:
    words = list(words)
    if word_order == "low_first":
        words = list(reversed(words))
    value = 0
    for w in words:
        value = (value << 16) | (int(w) & 0xFFFF)
    if signed and words and words[0] & 0x8000:
        value -= 1 << (16 * len(words))
    return value


@dataclass
class RegisterSpec:
    address: int
    words: int = 2
    word_order: str = "low_first"  # "low_first" or "high_first"
    register_type: str = "holding"  # "holding" or "input"
    wh_per_unit: float = 100.0  # 0.1 kWh units => 100 Wh per unit. For power registers: W per unit.
    signed: bool = False

    def value(self, words) -> float:
        return _combine(words, self.word_order, self.signed) * self.wh_per_unit

    def to_wh(self, words) -> int:
        return int(round(self.value(words)))


@dataclass
class Preset:
    counters: List[RegisterSpec] = field(default_factory=list)  # summed, in Wh
    power: Optional[RegisterSpec] = None  # for power integration, in W
    baudrate: int = 9600
    note: str = ""


PRESETS = {
    # Deye / Sunsynk hybrid (SG04LP1, SG04LP3 and similar), Modbus RTU or Solarman stick.
    "deye-hybrid": Preset([RegisterSpec(534, 2, "low_first", "holding", 100)]),
    # Deye / Sunsynk string (grid tie) inverters.
    "deye-string": Preset([RegisterSpec(63, 2, "low_first", "holding", 100)]),
    # Growatt grid tie, protocol v1.2x: "Eac total" input registers (0.1 kWh).
    "growatt-tl": Preset([RegisterSpec(55, 2, "high_first", "input", 100)]),
    # Felicity T-REX 5K/6K/10K (protocol IVGM5048 / IVGM10048): "PV Generated energy inquiry Total",
    # 64 bit Wh at 0x1156. Ships at 2400 baud.
    "felicity-trex": Preset([RegisterSpec(4438, 4, "high_first", "holding", 1)], baudrate=2400),
    # Felicity IVGM 8K / 15K / 20K: "PV Total Gen Energy" at 0x11C5 (0.1 kWh).
    "felicity-ivgm": Preset([RegisterSpec(4549, 2, "high_first", "holding", 100)]),
    # Felicity IVAM6048: PV1 + PV2 lifetime totals at 0x1195 and 0x1197 (0.1 kWh), summed.
    "felicity-ivam": Preset(
        [RegisterSpec(4501, 2, "high_first", "holding", 100), RegisterSpec(4503, 2, "high_first", "holding", 100)]
    ),
    # Felicity IVEM (IVEM3024, IVEM5048, IVEM6048, IVEM6048-II): no lifetime energy register is
    # documented, so the bridge integrates "PV Power Summary" (0x11A0, watts). RS232 on the RJ45 port.
    "felicity-ivem": Preset(power=RegisterSpec(4512, 1, "high_first", "holding", 1), note="power integration"),
}

# Register maps above come from the open source Felicity integrations
# github.com/partach/ha_felicity and github.com/luizcorreia/fsolar_esphome.


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


class Transport(Protocol):
    def read(self, spec: RegisterSpec) -> List[int]: ...


@dataclass
class ModbusTcpTransport:
    host: str
    port: int = 502
    unit_id: int = 1
    timeout_s: float = 5.0

    def read(self, spec: RegisterSpec) -> List[int]:
        from pymodbus.client import ModbusTcpClient

        client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout_s)
        if not client.connect():
            raise SourceError(f"cannot connect to Modbus TCP {self.host}:{self.port}")
        try:
            return _read(client, spec, self.unit_id)
        finally:
            client.close()


@dataclass
class ModbusRtuTransport:
    """USB RS485 or RS232 adapter on a Raspberry Pi or laptop."""

    port: str
    baudrate: int = 9600
    unit_id: int = 1
    parity: str = "N"
    stopbits: int = 1
    timeout_s: float = 3.0

    def read(self, spec: RegisterSpec) -> List[int]:
        from pymodbus.client import ModbusSerialClient

        client = ModbusSerialClient(
            port=self.port, baudrate=self.baudrate, parity=self.parity, stopbits=self.stopbits, bytesize=8, timeout=self.timeout_s
        )
        if not client.connect():
            raise SourceError(f"cannot open serial port {self.port}")
        try:
            return _read(client, spec, self.unit_id)
        finally:
            client.close()


@dataclass
class SolarmanTransport:
    """Solarman WiFi logger stick (Deye, Sunsynk and others), read over your LAN."""

    host: str
    logger_serial: int
    port: int = 8899
    unit_id: int = 1

    def read(self, spec: RegisterSpec) -> List[int]:
        from pysolarmanv5 import PySolarmanV5

        inv = PySolarmanV5(self.host, int(self.logger_serial), port=self.port, mb_slave_id=self.unit_id, socket_timeout=10)
        try:
            fn = inv.read_holding_registers if spec.register_type == "holding" else inv.read_input_registers
            return list(fn(register_addr=spec.address, quantity=spec.words))
        except Exception as e:  # noqa: BLE001
            raise SourceError(f"Solarman read failed: {e}") from e
        finally:
            try:
                inv.disconnect()
            except Exception:  # noqa: BLE001
                pass


def _read(client, spec: RegisterSpec, unit_id: int) -> List[int]:
    fn = client.read_holding_registers if spec.register_type == "holding" else client.read_input_registers
    try:
        rr = fn(spec.address, count=spec.words, device_id=unit_id)
    except TypeError:  # pymodbus < 3.9 names it slave
        rr = fn(spec.address, count=spec.words, slave=unit_id)
    if rr.isError():
        raise SourceError(f"Modbus read failed at register {spec.address}: {rr}")
    return list(rr.registers)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@dataclass
class CounterSource:
    """Lifetime energy counter(s) read straight from the inverter. Several are summed (PV1 + PV2)."""

    transport: Transport
    counters: List[RegisterSpec]
    method: str = "iot"

    def read_total_wh(self) -> int:
        return sum(spec.to_wh(self.transport.read(spec)) for spec in self.counters)


@dataclass
class PowerIntegrationSource:
    """Integrates PV power (W) sampled every few seconds into a Wh counter.

    Rules that keep it conservative:
      * trapezoid rule between consecutive samples
      * a gap longer than max_gap_s (missed samples, process stopped) adds nothing,
        so downtime is under reported, never invented
      * the counter is saved to disk after every sample, so restarts keep it
    """

    transport: Transport
    power: RegisterSpec
    state_path: str
    sample_s: float = 10.0
    max_gap_s: float = 60.0
    clock: callable = time.time
    method: str = "iot-integrated"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)

    def __post_init__(self):
        self.total_wh = 0.0
        self.last_t: Optional[float] = None
        self.last_w: Optional[float] = None
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                s = json.load(f)
            self.total_wh = float(s.get("total_wh", 0.0))

    def read_power_w(self) -> float:
        w = self.power.value(self.transport.read(self.power))
        return max(0.0, w)

    def sample(self) -> float:
        """Take one sample and integrate it. Returns the power read, in W."""
        w = self.read_power_w()
        t = self.clock()
        with self._lock:
            if self.last_t is not None:
                dt = t - self.last_t
                if 0 < dt <= self.max_gap_s:
                    self.total_wh += (self.last_w + w) / 2.0 * dt / 3600.0
            self.last_t, self.last_w = t, w
            self._save()
        return w

    def _save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"total_wh": self.total_wh}, f)
        os.replace(tmp, self.state_path)

    def read_total_wh(self) -> int:
        self.ensure_running()
        with self._lock:
            return int(self.total_wh)

    def ensure_running(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                try:
                    self.sample()
                except SourceError as e:
                    # The next good sample is more than max_gap_s later, so this gap adds 0 Wh.
                    log.warning("power sample failed: %s", e)
                self._stop.wait(self.sample_s)

        self._thread = threading.Thread(target=loop, name="pv-sampler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()


@dataclass
class ManualSource:
    """A reading typed in by a person from the inverter or meter screen, attested as method "manual"."""

    total_kwh: float
    method: str = "manual"

    def read_total_wh(self) -> int:
        if self.total_kwh < 0:
            raise SourceError("total_kwh must not be negative")
        return int(round(self.total_kwh * 1000))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _check(spec: RegisterSpec) -> RegisterSpec:
    if spec.word_order not in ("low_first", "high_first"):
        raise SourceError("word_order must be 'low_first' or 'high_first'")
    if spec.register_type not in ("holding", "input"):
        raise SourceError("register_type must be 'holding' or 'input'")
    return spec


def _custom_spec(cfg: dict) -> RegisterSpec:
    spec = RegisterSpec(address=int(cfg["register"]))
    for key in ("words", "word_order", "register_type", "wh_per_unit", "signed"):
        if key in cfg:
            setattr(spec, key, cfg[key])
    return _check(spec)


def _preset(cfg: dict) -> Optional[Preset]:
    name = cfg.get("preset")
    if name is None:
        return None
    if name not in PRESETS:
        raise SourceError(f"unknown preset {name!r}; choose one of {sorted(PRESETS)} or give a register")
    return PRESETS[name]


def build_transport(cfg: dict, preset: Optional[Preset] = None) -> Transport:
    kind = cfg.get("type")
    unit = int(cfg.get("unit_id", 1))
    if kind == "modbus-tcp":
        return ModbusTcpTransport(cfg["host"], int(cfg.get("port", 502)), unit)
    if kind == "modbus-rtu":
        baud = int(cfg.get("baudrate", preset.baudrate if preset else 9600))
        return ModbusRtuTransport(cfg["port"], baud, unit, cfg.get("parity", "N"), int(cfg.get("stopbits", 1)))
    if kind == "solarman":
        return SolarmanTransport(cfg["host"], int(cfg["logger_serial"]), int(cfg.get("port", 8899)), unit)
    raise SourceError(f"unknown source type {kind!r}; use modbus-tcp, modbus-rtu or solarman")


def build_source(cfg: dict, state_dir: str = ".") -> EnergySource:
    preset = _preset(cfg)
    transport = build_transport(cfg, preset)
    mode = cfg.get("mode") or ("power" if preset and preset.power and not preset.counters else "counter")

    if mode == "power":
        if "power_register" in cfg:
            power = _custom_spec({**cfg, "register": cfg["power_register"], "words": cfg.get("words", 1), "wh_per_unit": cfg.get("w_per_unit", 1)})
        elif preset and preset.power:
            power = replace(preset.power)
        else:
            raise SourceError("power integration needs a preset with a power register or 'power_register'")
        return PowerIntegrationSource(
            transport,
            power,
            state_path=os.path.join(state_dir, cfg.get("integration_state", "pv-integrator.json")),
            sample_s=float(cfg.get("sample_seconds", 10)),
            max_gap_s=float(cfg.get("max_gap_seconds", 60)),
        )

    if "register" in cfg:
        counters = [_custom_spec(cfg)]
    elif preset and preset.counters:
        counters = [replace(c) for c in preset.counters]
    else:
        raise SourceError("counter sources need a preset with a counter register or 'register'")
    return CounterSource(transport, counters)
