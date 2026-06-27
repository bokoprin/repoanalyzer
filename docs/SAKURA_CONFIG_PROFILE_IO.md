# Sakura-style settings / CShareData / profile / INI evidence

This note documents the lightweight semantic support for Sakura Editor style
settings persistence.

The goal is not to claim that every setting path is fully interpreted.  The goal
is to expose the important static evidence so an LLM can answer safely:

- entry points that load or save shared settings,
- the common `ShareData_IO_2(bool bRead)` profile-I/O core,
- read/write mode selection on `CDataProfile`,
- INI path resolution,
- profile read/write calls,
- section helpers such as `ShareData_IO_Common` and `ShareData_IO_Mru`,
- `GetDllShareData()` / `m_Common` / history-setting access,
- language-setting refresh side effects.

## Extracted relation predicates

The C++ semantic layer emits relation facts such as:

- `loads_shared_settings`
- `saves_shared_settings`
- `runs_profile_io`
- `resolves_ini_path`
- `selects_profile_mode`
- `reads_profile`
- `writes_profile`
- `maps_profile_key`
- `checks_profile_mode`
- `accesses_shared_data`
- `accesses_common_setting`
- `loads_config_section`
- `applies_language_setting`
- `refreshes_shared_strings`
- `backs_up_ini_file`

These are semantic evidence relations.  They should not be presented as stronger
than the source supports.  In particular, `ShareData_IO_2` is a read/write core
whose behavior depends on `bRead`, so an answer should describe read and write
branches separately.

## Deterministic evidence intent

`collect-evidence` recognizes questions like:

```text
設定読み書き / CShareData / CommonSetting / profile / ini系はどう行われる？
```

and returns `interpreted_intent=config_profile_io` with traces such as:

```text
load_share_data_trace:
  CShareData_IO::LoadShareData
    -> CShareData_IO::ShareData_IO_2

save_share_data_trace:
  CShareData_IO::SaveShareData
    -> CShareData_IO::ShareData_IO_2

profile_core_io_trace:
  CShareData_IO::ShareData_IO_2
    -> GetDllShareData
    -> CDataProfile::SetReadingMode / SetWritingMode
    -> GetIniFileNameForIO
    -> CDataProfile::ReadProfile
    -> CDataProfile::IOProfileData
    -> CShareData_IO::ShareData_IO_Common
    -> CDataProfile::WriteProfile

mru_section_profile_mapping_trace:
  CShareData_IO::ShareData_IO_Mru
    -> GetDllShareData
    -> CDataProfile::IOProfileData
    -> CDataProfile::IsReadingMode
```

## Known limits

- The current support is pattern-based and evidence-oriented.
- It does not fully parse every profile key name or every settings struct field.
- It does not prove runtime branch reachability beyond the static branch markers.
- It distinguishes semantic markers such as `m_Common` access and INI-path markers
  from normal function calls.
