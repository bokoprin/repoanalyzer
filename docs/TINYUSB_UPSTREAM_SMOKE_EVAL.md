# TinyUSB upstream smoke/profile eval

Batch 9 adds a smoke evaluation path for a real TinyUSB checkout.  The compact
fixtures remain the fast regression suite; the upstream smoke path checks that
those semantics still match the real TinyUSB source tree for representative
profiles.

## Profiles

`repoanalyzer real_repo_eval.tinyusb_upstream` generates four target profiles:

- `tinyusb_upstream_device_cdc_msc`
- `tinyusb_upstream_host_cdc_msc_hid`
- `tinyusb_upstream_device_hid_composite`
- `tinyusb_upstream_typec_power_delivery`

The generated files are written to `.repoanalyzer-smoke/` inside the TinyUSB
checkout:

- `compile_commands.<profile>.json`
- `repoanalyzer.<profile>.yml`
- `cases.<profile>.yaml`

These files are generated artifacts and do not need to be committed to TinyUSB.

## Prepare only

```bash
python -m repoanalyzer.cli tinyusb-upstream-smoke-prepare /path/to/tinyusb
```

## Run one profile

Run one profile at a time. Each profile intentionally re-ingests the checkout
with a different target profile, so separate commands keep memory and timings
predictable.

```bash
python -m repoanalyzer.cli tinyusb-upstream-smoke \
  /path/to/tinyusb \
  --profile tinyusb_upstream_device_cdc_msc \
  --output json
```

## Pytest integration

The normal regression suite only verifies that the smoke profiles can be
generated.  To run the real upstream smoke test, provide a TinyUSB checkout:

```bash
REPOANALYZER_TINYUSB_UPSTREAM=/path/to/tinyusb \
  python -m pytest -q tests/test_phase7_tinyusb_upstream_smoke_eval.py -m upstream
```

## Running all representative profiles

Run the four profiles as separate commands:

```bash
for profile in \
  tinyusb_upstream_device_cdc_msc \
  tinyusb_upstream_host_cdc_msc_hid \
  tinyusb_upstream_device_hid_composite \
  tinyusb_upstream_typec_power_delivery
do
  python -m repoanalyzer.cli tinyusb-upstream-smoke /path/to/tinyusb --profile "$profile"
done
```

## Current smoke expectations

The upstream smoke eval is intentionally looser than compact fixtures.  Real
TinyUSB headers and implementation files contain include guards, debug guards,
and target-specific controller code, so some evidence is expected to be
`conditional` rather than fully `supported`.  The smoke goal is to detect gross
breakage in target-profile selection and semantic extraction on real TinyUSB
source, not to turn repoanalyzer into a full USB specification validator.
