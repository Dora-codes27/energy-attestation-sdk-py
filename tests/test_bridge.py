"""Bridge tests: a real Modbus TCP server stands in for the inverter, and the
attestations go to the real contracts on the local chain."""

from __future__ import annotations

import socketserver
import struct
import threading

import pytest

from energy_attestation import EnergyType
from energy_attestation.bridge import Bridge, PowerIntegrationSource, build_source
from energy_attestation.bridge.sources import _combine
from conftest import DEPLOYMENT, make_sdk

pytestmark = pytest.mark.skipif(not DEPLOYMENT, reason="set EAS_DEPLOYMENT to a localchain deployment json")


def test_word_order():
    assert _combine([0x0002, 0x0001], "low_first") == 0x00010002
    assert _combine([0x0001, 0x0002], "high_first") == 0x00010002


class FakeClock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class _ModbusTcpHandler(socketserver.BaseRequestHandler):
    """Minimal Modbus TCP slave: answers read holding (0x03) and read input (0x04) registers."""

    def handle(self):
        regs = self.server.registers
        while True:
            hdr = self.request.recv(7)
            if len(hdr) < 7:
                return
            tid, pid, length, unit = struct.unpack(">HHHB", hdr)
            pdu = self.request.recv(length - 1)
            fn = pdu[0]
            if fn in (3, 4):
                addr, count = struct.unpack(">HH", pdu[1:5])
                values = [regs.get(addr + i, 0) for i in range(count)]
                body = bytes([fn, 2 * count]) + struct.pack(">" + "H" * count, *values)
            else:
                body = bytes([fn | 0x80, 1])  # illegal function
            self.request.sendall(struct.pack(">HHHB", tid, pid, len(body) + 1, unit) + body)


@pytest.fixture(scope="module")
def inverter():
    """A Modbus TCP device holding a Deye style lifetime counter at 534-535 (0.1 kWh, low word first)."""
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _ModbusTcpHandler)
    server.daemon_threads = True
    server.registers = {}
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def set_kwh(kwh: float):
        units = int(round(kwh * 10))
        server.registers[534] = units & 0xFFFF
        server.registers[535] = units >> 16

    set_kwh.registers = server.registers
    yield server.server_address[1], set_kwh
    server.shutdown()


def test_modbus_source_reads_real_protocol(inverter):
    port, set_kwh = inverter
    set_kwh(12345.6)
    src = build_source({"type": "modbus-tcp", "host": "127.0.0.1", "port": port, "preset": "deye-hybrid"})
    assert src.read_total_wh() == 12_345_600
    set_kwh(7000.1)  # crosses the 16 bit boundary in units
    assert src.read_total_wh() == 7_000_100


def test_bridge_end_to_end(dep, inverter, tmp_path):
    port, set_kwh = inverter
    owner, device = make_sdk(dep, 1), make_sdk(dep, 2)
    w = owner.watchers.create_watcher("Bridge Test Site")
    p = owner.projects.create_project(w.watcher_id, "Deye 8kW", EnergyType.SOLAR_PV)
    owner.attesters.add_attester(p.project_id, device.address)

    clock = FakeClock(1_761_640_000)  # not hour aligned on purpose
    src = build_source({"type": "modbus-tcp", "host": "127.0.0.1", "port": port, "preset": "deye-hybrid"})
    state = str(tmp_path / "state.json")
    bridge = Bridge(device, src, p.project_id, state, clock=clock)

    set_kwh(1000.0)
    r = bridge.tick()
    assert r.action == "baseline"
    first_hour = 1_761_640_000 + (-1_761_640_000) % 3600
    assert bridge.state.baseline_ts == first_hour

    clock.t = first_hour + 1800
    assert bridge.tick().action == "waiting"

    clock.t = first_hour + 3600 + 30
    set_kwh(1003.2)
    r = bridge.tick()
    assert r.action == "attested" and r.energy_wh == 3200 and (r.from_ts, r.to_ts) == (first_hour, first_hour + 3600)

    # Three hours with no successful tick (power cut): one honest 3 hour attestation, nothing invented.
    clock.t = first_hour + 4 * 3600 + 10
    set_kwh(1010.0)
    r = bridge.tick()
    assert r.action == "attested" and r.energy_wh == 6800 and r.to_ts - r.from_ts == 3 * 3600

    # A restarted process picks up from the saved state.
    bridge2 = Bridge(device, src, p.project_id, state, clock=clock)
    clock.t = first_hour + 5 * 3600 + 5
    set_kwh(1012.5)
    assert bridge2.tick().energy_wh == 2500

    # Counter goes backwards (inverter swapped): nothing attested.
    clock.t = first_hour + 6 * 3600 + 5
    set_kwh(3.0)
    assert bridge2.tick().action == "reset"
    assert device.read.get_total_generated_energy(p.project_id) == 3200 + 6800 + 2500

    # Dry run sends nothing.
    clock.t = first_hour + 7 * 3600 + 5
    set_kwh(4.5)
    dry = Bridge(device, src, p.project_id, state, clock=clock, dry_run=True)
    r = dry.tick()
    assert r.action == "dry-run" and r.energy_wh == 1500
    assert device.read.get_project_last_timestamp(p.project_id) == first_hour + 5 * 3600


# ---------------------------------------------------------------------------
# Felicity Solar
# ---------------------------------------------------------------------------


def _put(regs, address, value, words):
    for i in range(words):
        regs[address + i] = (value >> (16 * (words - 1 - i))) & 0xFFFF  # high word first


def test_felicity_trex_64bit_wh_counter(inverter):
    port, set_kwh = inverter
    _put(set_kwh.registers, 4438, 9_876_543_210, 4)  # Wh, 64 bit
    src = build_source({"type": "modbus-tcp", "host": "127.0.0.1", "port": port, "preset": "felicity-trex"})
    assert src.read_total_wh() == 9_876_543_210


def test_felicity_ivam_sums_both_strings(inverter):
    port, set_kwh = inverter
    _put(set_kwh.registers, 4501, 12_345, 2)  # PV1 1234.5 kWh
    _put(set_kwh.registers, 4503, 70_001, 2)  # PV2 7000.1 kWh
    src = build_source({"type": "modbus-tcp", "host": "127.0.0.1", "port": port, "preset": "felicity-ivam"})
    assert src.read_total_wh() == 1_234_500 + 7_000_100


def test_felicity_ivgm_total(inverter):
    port, set_kwh = inverter
    _put(set_kwh.registers, 4549, 4_321, 2)
    src = build_source({"type": "modbus-tcp", "host": "127.0.0.1", "port": port, "preset": "felicity-ivgm"})
    assert src.read_total_wh() == 432_100


def test_felicity_ivem_power_integration(inverter, tmp_path):
    port, set_kwh = inverter
    clock = FakeClock(1_000_000)
    src = build_source({"type": "modbus-tcp", "host": "127.0.0.1", "port": port, "preset": "felicity-ivem"}, str(tmp_path))
    assert isinstance(src, PowerIntegrationSource) and src.method == "iot-integrated"
    src.clock = clock

    def at(t, watts):
        clock.t = t
        set_kwh.registers[4512] = watts
        src.sample()

    at(1_000_000, 3000)
    at(1_000_010, 3000)  # 10 s at 3 kW
    at(1_000_020, 1000)  # ramp 3 kW to 1 kW over 10 s
    assert round(src.total_wh, 6) == round(3000 * 10 / 3600 + 2000 * 10 / 3600, 6)

    before = src.total_wh
    at(1_000_500, 4000)  # 480 s gap: inverter link lost, so nothing is added
    assert src.total_wh == before
    at(1_000_510, 4000)
    assert round(src.total_wh - before, 6) == round(4000 * 10 / 3600, 6)

    # Counter survives a restart.
    again = build_source({"type": "modbus-tcp", "host": "127.0.0.1", "port": port, "preset": "felicity-ivem"}, str(tmp_path))
    assert int(again.total_wh) == int(src.total_wh)
