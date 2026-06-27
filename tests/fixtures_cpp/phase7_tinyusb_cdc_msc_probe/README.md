# Phase7 TinyUSB CDC MSC probe fixture

This compact fixture is derived from the uploaded TinyUSB `examples/device/cdc_msc` shape. It keeps Batch 1 small: the target profile fixes one TinyUSB device build so repoanalyzer can evaluate active source selection and build macro evidence before deeper USB descriptor/callback/dispatch semantics are added.

Target scope:

- example: `examples/device/cdc_msc`
- role: device
- board: `stm32f407disco`
- RTOS: none
- selected controller port: `src/portable/synopsys/dwc2`
- classes enabled by `tusb_config.h`: CDC and MSC
- classes intentionally inactive: HID, host, dual-role, type-c, non-selected controller ports

Later batches should build on this fixture for descriptor macros, weak callback override semantics, and class driver table/endpoint dispatch evidence.
