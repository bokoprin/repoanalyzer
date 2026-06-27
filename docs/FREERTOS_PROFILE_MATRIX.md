# FreeRTOS Profile Matrix

`profile-matrix` runs the same C/C++ repository through multiple `repoanalyzer.yml` target profiles and compares build-sensitive evidence across those profiles.

This is intended for FreeRTOS-style repositories where one source tree contains many valid target builds:

- `configUSE_TIMERS=1/0`
- `configSUPPORT_DYNAMIC_ALLOCATION=1/0`
- `configSUPPORT_STATIC_ALLOCATION=1/0`
- selected `portable/GCC/...` port
- selected `portable/MemMang/heap_*.c`

## CLI

```bash
python3 -m repoanalyzer.cli profile-matrix <repo> <matrix.yml>
```

The command copies the repository once per profile, ingests each copy with the specified config, then reports:

- profile metadata and macros
- allocation profile
- target symbol/file active status
- changed/stable targets across profiles
- answer-contract build context for sample answers

## Matrix schema

```yaml
id: freertos_profile_matrix
profiles:
  - id: timers_on
    config: repoanalyzer.yml
  - id: timers_off
    config: repoanalyzer_timers_off.yml

targets:
  - id: timer_service_task
    claim_type: build_active
    subject: xTimerCreateTimerTask
  - id: selected_heap
    claim_type: file_active
    subject: portable/MemMang/heap_4.c
    object: active

answer_contracts:
  - id: allocation_contract
    text: dynamic allocation is disabled in the target profile. static allocation is enabled in the target profile.
```

## Why this matters

A single FreeRTOS checkout contains code that is source-present but target-inactive for many builds. The matrix makes that distinction explicit, so an LLM can answer questions with profile scope instead of mixing incompatible builds.
