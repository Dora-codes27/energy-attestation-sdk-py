# energy-attestation-sdk (Python)

Python SDK for the [Energy Attestation Service](https://attest.energy), the on chain public good built by [Suno](https://suno.finance) that lets any energy project publish its generation and consumption data through the [Ethereum Attestation Service](https://attest.org).

It mirrors the official TypeScript SDK ([energy-attestation-sdk-js](https://github.com/suno-finance/energy-attestation-sdk-js) v1.2.0) method for method, and adds an **inverter bridge** that reads a real solar inverter and attests its output every hour.

Why Python: most solar monitoring runs on Raspberry Pis, data loggers and Python tooling around Modbus inverters. This lets those projects join the standard without leaving their stack.

## Live

A real Felicity IVEM6048-II 6kW inverter in Nigeria is attesting on Suno's Polygon Amoy deployment: project #15 "Felicity Solar".

* First clean record: 1,385 Wh for 09:30 to 10:30 on 29 October 2026, method `estimated` (seven PV power readings from the inverter screen)
* [View the attestation on easscan.org](https://polygon-amoy.easscan.org/attestation/view/0xeb611b0689d9cb7564788837f92be83d500d4da00b477e66bb6da7f226664307)

## Install

Not on PyPI yet. Install from this repository (Python 3.9+, web3.py 7 or 8):

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[modbus]"
energy-bridge --help
```

## Quick start

```python
import os, time
from energy_attestation import EnergySDK, Network, EnergyType, AttestParams, Interval

owner = EnergySDK.from_private_key(os.environ["OWNER_PRIVATE_KEY"], Network.CELO)

# 1. Register your organization and a solar project (one time)
w = owner.watchers.create_watcher("Felicity Solar")
p = owner.projects.create_project(w.watcher_id, "Rooftop 6kW", EnergyType.SOLAR_PV)

# 2. Authorize the device wallet that will sign readings
device = EnergySDK.from_private_key(os.environ["ATTESTER_PRIVATE_KEY"], Network.CELO)
owner.attesters.add_attester(p.project_id, device.address)

# 3. Attest four hourly readings, in Wh (not kWh)
start = int(time.time()) // 3600 * 3600 - 4 * 3600
res = device.attestations.attest(AttestParams(
    project_id=p.project_id,
    readings=[1500, 1800, 2100, 1900],
    reading_interval_minutes=Interval.HOURLY,
    from_timestamp=start,
    method="iot",
))
print(res.uid, res.tx_hash)

# 4. Read it back (free view calls)
stats = device.read.get_project_stats(p.project_id)
print(stats.total_generated, "Wh attested")
```

Attestations form a gapless chain per project. The next one must start where the last one ended, which you can get from `read.get_project_last_timestamp(project_id)`.

## API

Same modules and behavior as the JS SDK, in snake_case:

| Module | Methods |
|---|---|
| `sdk.watchers` | `create_watcher`, `transfer_watcher_ownership`, `estimate_*` |
| `sdk.projects` | `create_project`, `deregister_project`, `transfer_project`, `set_project_metadata_uri`, `estimate_*` |
| `sdk.attesters` | `add_attester(s)`, `remove_attester(s)`, `add_watcher_attester`, `remove_watcher_attester`, `estimate_*` |
| `sdk.attestations` | `attest`, `attest_batch`, `attest_zero_period`, `overwrite_attestation`, `revoke_attestation`, `estimate_*` |
| `sdk.energy_types` | `register_energy_type`, `remove_energy_type`, `transfer_energy_type_admin` (admin only) |
| `sdk.read` | every view function on the registry, plus `get_attestation_data`, `get_project_stats`, `get_watcher_stats` |
| `EnergyQuery` | subgraph reads: `get_protocol`, `get_watchers`, `get_projects`, `get_attestations`, `get_daily_snapshots`, `iterate_*` |

Errors are typed. Contract reverts are decoded from both the registry and resolver ABIs:

```python
from energy_attestation import ContractRevertError, ContractErrorCode

try:
    device.attestations.attest(params)
except ContractRevertError as e:
    if e.error_name == ContractErrorCode.NonSequentialAttestation:
        print("start at", e.error_args["expectedFrom"])
```

`ConfigurationError` is raised before any transaction is sent (bad params, wrong chain). `TransactionError` covers transport failures.

Networks: `Network.CELO`, `Network.POLYGON`, `Network.AMOY` (testnet). Addresses and schema UIDs resolve automatically. Pass `rpc_url` for your own endpoint in production.

## Inverter bridge

`energy-bridge` turns a real inverter into an attester. It reads the inverter's lifetime energy counter and attests the difference every hour.

It is built to be trusted:

* It always starts at the on chain chain tip, so nothing is double counted or skipped.
* If the device misses hours (power cut, no internet), it attests one honest longer period instead of inventing hourly numbers.
* It never attests a period that ends in the future.
* If the counter goes backwards (inverter replaced), it attests nothing and re-baselines.
* State is saved after every attestation, so a reboot picks up where it left off.

Supported sources:

| `type` | For |
|---|---|
| `solarman` | Deye, Sunsynk and others with a Solarman WiFi logger stick, read over your LAN |
| `modbus-tcp` | Inverters or meters on Modbus TCP, or an RS485 to Ethernet gateway |
| `modbus-rtu` | Inverter wired to a Raspberry Pi with a USB RS485 adapter |
| `manual` | No logger at all: type the lifetime kWh from the inverter screen once a day |
| `estimate` command | No counter and no cable: average PV kW screen readings over a period |

Presets: `deye-hybrid`, `deye-string`, `growatt-tl`, `felicity-trex`, `felicity-ivgm`, `felicity-ivam`, `felicity-ivem`. Register maps vary by model and firmware, so always check with `energy-bridge read` that the number matches your inverter's screen. You can set `register`, `words`, `word_order`, `register_type` and `wh_per_unit` yourself for any other device.

### Felicity Solar

Felicity inverters are everywhere in Nigeria, so they get first class support. Register maps come from the open source Felicity integrations [ha_felicity](https://github.com/partach/ha_felicity) and [fsolar_esphome](https://github.com/luizcorreia/fsolar_esphome).

| Model (check the label on the side) | Preset | How it is read |
|---|---|---|
| T-REX 5K / 6K / 10K (IVGM5048, IVGM6048, IVGM10048) | `felicity-trex` | Lifetime PV Wh counter. Ships at **2400 baud** |
| IVGM 8K / 15K / 20K | `felicity-ivgm` | Lifetime PV counter (0.1 kWh) |
| IVAM6048 | `felicity-ivam` | PV1 + PV2 lifetime counters, summed |
| IVEM3024, IVEM5048, IVEM6048, IVEM6048-II | `felicity-ivem` | Power integration (see below) |

The IVEM series exposes PV power but no documented lifetime energy register, so the bridge samples PV watts every 10 seconds and adds them up. To stay conservative, any gap longer than 60 seconds adds nothing, so downtime is under reported, never invented. These attestations carry method `iot-integrated`, so anyone reading the chain can see how the number was produced.

Wiring: the IVEM RJ45 port speaks **RS232** (pin 1 data out, pin 2 data in, pin 8 ground), 9600 baud, 8N1, unit ID 1. A USB to RS232 adapter on a laptop or Raspberry Pi works; use `examples/bridge.felicity-ivem.json`. Do not connect pin 3 (it carries about 10 V).

### Setup

```bash
export OWNER_PRIVATE_KEY=0x...     # owns the project, keep it off the device
export ATTESTER_PRIVATE_KEY=0x...  # lives on the device, only allowed to attest
# Windows PowerShell: $env:OWNER_PRIVATE_KEY="0x..."  and  $env:ATTESTER_PRIVATE_KEY="0x..."

energy-bridge setup --network celo --watcher-name "My Solar" --project-name "Rooftop 5kW"
cp examples/bridge.example.json bridge.json   # put the project_id from setup in it
energy-bridge read bridge.json                # check the counter matches the screen
energy-bridge run bridge.json --dry-run       # see what would be attested
energy-bridge run bridge.json                 # run for real (or use the systemd unit)
energy-bridge status bridge.json
```

No logger? Use manual mode once a day:

```bash
energy-bridge manual bridge.json --total-kwh 2041.7
```

No counter and no cable (for example a Felicity IVEM before its cable is fitted)? Read the PV kW figure off the screen a few times during a period, then attest the average, labeled `estimated`:

```bash
energy-bridge estimate bridge.json --kw 0.777 1.34 2.27 2.32
energy-bridge estimate bridge.json --start 09:30 --end 10:30 --kw 0.777 1.34 2.27 2.32 0.954 1.06 0.976
```

By default it covers the last whole hour. `--start` and `--end` set a custom window; the end must already have passed, and once a project has readings the start must be where the record left off, so it stays gapless. It shows the period and the estimate and asks before sending anything.

Gas on Celo is a fraction of a cent per attestation, so an hourly bridge costs very little to run.

## Tests

The test suite runs against the real `EnergyRegistry`, `EnergyAttestationResolver` and EAS contracts on a local chain, not mocks, and checks the encoding byte for byte against ethers.js. The bridge tests read a real Modbus TCP device.

```bash
npx hardhat node                                   # in a clone of energy-attestation-service
node tests/compile_contracts.cjs path/to/energy-attestation-service artifacts.json
python tests/localchain.py artifacts.json > deployment.json
EAS_DEPLOYMENT=deployment.json ETHERS_DIR=path/to/node_modules pytest
```

## License

MIT
