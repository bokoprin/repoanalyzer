# Cline batch prompt: RepoAnalyzer TinyUSB golden E2E

# RepoAnalyzer TinyUSB golden E2E batch rules

あなたは TinyUSB を対象に repoanalyzer MCP を使って回答します。

## 絶対ルール

1. 各caseで、まず repoanalyzer MCP の `collect_evidence` を使う。
2. 回答前に、根拠として使うファイル行を必ず `read_file_range` で読み直す。
3. マクロ定義場所、callback定義場所、call/dispatch関係を述べる場合、推測や一般知識で補完しない。
4. 根拠が弱い場合は `unknown` または `conditional` と明記する。
5. build/profile/guard依存の話は `conditional` として扱う。
6. 最終出力は JSONL。1 case = 1 JSON object = 1 line。
7. Markdownの説明文、コードフェンス、箇条書きの外側説明は出力しない。
8. 長いコード全文を貼らない。必要なら短い `quote_excerpt` だけにする。
9. `tool_trace` には実際に使ったtoolを記録する。
10. read_file_rangeしていないファイル・行番号を根拠として断定しない。

## 出力先

可能なら以下に保存してください。

- Cline: `eval/outputs/tinyusb_answers_cline.jsonl`
- Qwen Code: `eval/outputs/tinyusb_answers_qwen_code.jsonl`

ファイル保存が難しければ、JSONLをチャット本文にそのまま出力してください。


## agent metadata

agent_id: `cline`
model: `qwen3.5-35b`
repo target: `C:\shinsuke\app\tinyusb`
repoanalyzer MCP server: `repoanalyzer-tinyusb`

## task

以下の10件を順番に評価してください。
各caseで、repoanalyzer MCPを使い、`collect_evidence` → 必要な `find_*` → `read_file_range` → JSONL回答、の順で進めてください。

## JSONL schema summary

各行は以下のキーを持つJSON objectにしてください。

- run_id
- agent_id
- model
- case_id
- profile
- question
- tool_trace
- evidence
- answer
- verdict
- confidence
- self_check
- known_limitations
- repoanalyzer_fix_suggestions
- agent_notes

## cases

## tinyusb_desc_001

profile: tinyusb_upstream_device_cdc_msc
category: descriptor
difficulty: basic
question: TinyUSBのCDC/MSC configuration descriptorはどこで定義されている？
required_tools: collect_evidence;read_file_range
required_files: examples/device/cdc_msc/src/usb_descriptors.c
required_symbols: desc_fs_configuration;desc_hs_configuration;desc_other_speed_config;tud_descriptor_configuration_cb;ITF_NUM_CDC;ITF_NUM_MSC
expected_points: CDC/MSC exampleのconfiguration descriptor配列がexamples/device/cdc_msc/src/usb_descriptors.cにあること。FS用desc_fs_configuration、HS用desc_hs_configuration、other-speed用desc_other_speed_config、取得callbackのtud_descriptor_configuration_cbを区別して説明すること。
conditional_points: HS/other-speed descriptorはTUD_OPT_HIGH_SPEEDなどbuild/target条件に依存する可能性を述べること。
forbidden_claims: 根拠行を読まずに行番号を断定する;TUD_CDC_DESCRIPTOR/TUD_MSC_DESCRIPTORの定義場所をsrc/class/cdc/cdc.hやsrc/class/msc/msc.hと断定する
evaluation_focus: read_file_rangeでusb_descriptors.cの該当行を読んだか。場所、配列名、callback、条件付き要素を区別できたか。
## tinyusb_desc_002

profile: tinyusb_upstream_device_cdc_msc
category: descriptor_macro
difficulty: basic
question: TUD_CONFIG_DESCRIPTOR、TUD_CDC_DESCRIPTOR、TUD_MSC_DESCRIPTORのマクロ定義はどこにある？example側で使われる箇所と、マクロ定義側の両方を確認して答えて。
required_tools: collect_evidence;find_definitions;read_file_range
required_files: examples/device/cdc_msc/src/usb_descriptors.c;src/device/usbd.h
required_symbols: TUD_CONFIG_DESCRIPTOR;TUD_CDC_DESCRIPTOR;TUD_MSC_DESCRIPTOR
expected_points: example側の利用箇所はusb_descriptors.c内のconfiguration descriptor配列。マクロ定義はTinyUSB device descriptor template側、現在のupstreamではsrc/device/usbd.h側で確認すること。
conditional_points: include経路はtusb.h等を経由する可能性があるため、直接includeだけでなく定義ファイルを根拠で確認すること。
forbidden_claims: src/class/cdc/cdc.hにTUD_CDC_DESCRIPTORが定義されていると根拠なしに断定する;src/class/msc/msc.hにTUD_MSC_DESCRIPTORが定義されていると根拠なしに断定する
evaluation_focus: find_definitionsまたはread_file_rangeでマクロ定義ファイルを確認したか。前回の誤りが再発しないか。
## tinyusb_desc_003

profile: tinyusb_upstream_device_cdc_msc
category: descriptor_callback
difficulty: basic
question: tud_descriptor_configuration_cb(uint8_t index)はどのdescriptorを返す？Full-speed/High-speed/Other-speedの扱いを根拠行つきで説明して。
required_tools: collect_evidence;read_file_range
required_files: examples/device/cdc_msc/src/usb_descriptors.c
required_symbols: tud_descriptor_configuration_cb;tud_descriptor_other_speed_configuration_cb;desc_fs_configuration;desc_hs_configuration;desc_other_speed_config;tud_speed_get;TUSB_SPEED_HIGH
expected_points: tud_descriptor_configuration_cbは速度に応じてdesc_hs_configurationまたはdesc_fs_configurationを返す。other-speedは別callbackでdesc_other_speed_configを生成/返す。
conditional_points: HS/other-speed関連はTUD_OPT_HIGH_SPEED条件下の可能性があることを述べる。
forbidden_claims: index引数でdescriptor配列を選ぶと断定する;other-speedもtud_descriptor_configuration_cbが直接返すと断定する
evaluation_focus: callbackの実装行を読み、index未使用/速度分岐/other-speed別callbackを区別できるか。
## tinyusb_event_001

profile: tinyusb_upstream_device_cdc_msc
category: device_event_queue
difficulty: intermediate
question: dcd_event_handlerからtud_taskまで、TinyUSB device stackではイベントはどのように渡される？OSAL queueを含めて根拠行つきで説明して。
required_tools: collect_evidence;find_callers;find_callees;read_file_range
required_files: src/device/usbd.c;src/device/dcd.h
required_symbols: dcd_event_handler;tud_task;osal_queue_send;osal_queue_receive;_usbd_q
expected_points: DCD側イベントはdcd_event_handlerでdevice stackへ入り、キューへ送られ、tud_task側で受信/処理される流れを説明する。
conditional_points: OSAL実装やqueue実体はtarget/profileによって異なる可能性があるため、抽象queue操作として説明する。
forbidden_claims: ISRからclass driver callbackが常に直接呼ばれると断定する;キューを介さない同期処理だと断定する
evaluation_focus: event deferralを説明できるか。直接呼び出しとqueue経由処理を混同しないか。
## tinyusb_dispatch_001

profile: tinyusb_upstream_device_cdc_msc
category: endpoint_dispatch
difficulty: intermediate
question: endpoint transfer完了イベントは、どのようにclass driverのxfer_cbへdispatchされる？endpoint mapやdriver tableを含めて根拠行つきで説明して。
required_tools: collect_evidence;find_callers;find_callees;read_file_range
required_files: src/device/usbd.c
required_symbols: dcd_event_xfer_complete;_usbd_driver;get_driver;ep2drv;itf2drv;xfer_cb
expected_points: transfer completeイベント処理でendpointからdriverを引き、driver tableのxfer_cbへ間接dispatchされる流れを説明する。
conditional_points: 具体的なclass driverはendpoint/interfaceのbinding状態に依存する。
forbidden_claims: CDC/MSCのxfer_cbが固定で直接呼ばれると断定する;endpoint番号だけで常にclassが一意に決まると断定する
evaluation_focus: driver table、endpoint/interface mapping、indirect dispatchの区別ができるか。
## tinyusb_xfer_001

profile: tinyusb_upstream_device_cdc_msc
category: transfer_submit
difficulty: intermediate
question: usbd_edpt_xferは最終的にどのDCD境界関数へ到達する？busy/claim処理も含めて根拠行つきで説明して。
required_tools: collect_evidence;find_callees;read_file_range
required_files: src/device/usbd.c;src/device/dcd.h;src/portable/synopsys/dwc2/dcd_dwc2.c
required_symbols: usbd_edpt_xfer;usbd_edpt_claim;usbd_edpt_release;dcd_edpt_xfer
expected_points: usbd_edpt_xferはendpoint claim/busy確認などを経て、DCD抽象境界のdcd_edpt_xferへ転送要求を渡す。
conditional_points: 実際のportable実装は選択port/profileに依存する。今回profileではDWC2系がactiveになる可能性が高い。
forbidden_claims: usbd_edpt_xferがUSB hardware registerを直接操作すると断定する;portable port非依存の実装詳細を断定する
evaluation_focus: device coreとDCD境界を分離して説明できるか。
## tinyusb_cdc_001

profile: tinyusb_upstream_device_cdc_msc
category: cdc_class
difficulty: intermediate
question: tud_cdc_writeはどこで定義され、どのようにendpoint transferへつながる？根拠行つきで説明して。
required_tools: collect_evidence;find_definitions;find_callees;read_file_range
required_files: src/class/cdc/cdc_device.c;src/class/cdc/cdc_device.h;src/device/usbd.c
required_symbols: tud_cdc_write;tud_cdc_n_write;usbd_edpt_xfer
expected_points: CDC device classのwrite APIはcdc_device側にあり、内部buffer/flush経由でdevice endpoint transferへつながる流れを説明する。
conditional_points: 実際の送信完了や再送タイミングはendpoint busy状態やclass driver状態に依存する。
forbidden_claims: tud_cdc_writeが即座にUSB hostへ同期送信完了すると断定する;アプリcallbackだけで転送されると断定する
evaluation_focus: API定義場所と下位endpoint transferへの接続を混同しないか。
## tinyusb_msc_001

profile: tinyusb_upstream_device_cdc_msc
category: msc_class
difficulty: intermediate
question: MSC READ10はTinyUSB内部からどのapplication callbackへ渡される？example側の実装場所も含めて根拠行つきで説明して。
required_tools: collect_evidence;find_definitions;find_references;read_file_range
required_files: src/class/msc/msc_device.c;examples/device/cdc_msc/src/msc_disk.c
required_symbols: SCSI_CMD_READ_10;tud_msc_read10_cb
expected_points: MSC class処理内でREAD10 SCSI commandを処理し、application側のtud_msc_read10_cbへ委譲する。cdc_msc exampleではmsc_disk.cにcallback実装がある。
conditional_points: storage backendやread/write処理内容はexample実装に依存する。
forbidden_claims: TinyUSB coreが常に固定ディスク内容を直接読むと断定する;application callbackが不要だと断定する
evaluation_focus: class internal処理とapplication override/callback実装の対応を説明できるか。
## tinyusb_callback_001

profile: tinyusb_upstream_device_cdc_msc
category: weak_callback
difficulty: intermediate
question: cdc_msc exampleでは、device mount/unmount/suspend/resume系callbackはどこで実装される？TinyUSB側のweak/default callbackとの関係が分かる範囲で根拠行つきで説明して。
required_tools: collect_evidence;find_definitions;find_references;read_file_range
required_files: examples/device/cdc_msc/src/main.c;src/device/usbd.c
required_symbols: tud_mount_cb;tud_umount_cb;tud_suspend_cb;tud_resume_cb;TU_ATTR_WEAK
expected_points: example側main.cにapplication callback実装があり、TinyUSB側にはweak/default callbackまたはcallback宣言がある場合、そのoverride関係を根拠に基づいて説明する。
conditional_points: weak/defaultの有無や場所はcallbackごとに異なる可能性があるため、読めた範囲でsupported/unknownを分ける。
forbidden_claims: すべてのcallbackが必ずweak defaultを持つと断定する;根拠なしにoverride関係を断定する
evaluation_focus: weak/default/application実装を区別し、unknownを安全に扱えるか。
## tinyusb_conditional_001

profile: tinyusb_upstream_device_cdc_msc
category: build_conditional
difficulty: advanced
question: CDC/MSC descriptor周辺でTUD_OPT_HIGH_SPEEDが有効な場合と無効な場合で、コード上何が変わる？conditionalとして根拠行つきで説明して。
required_tools: collect_evidence;read_file_range
required_files: examples/device/cdc_msc/src/usb_descriptors.c
required_symbols: TUD_OPT_HIGH_SPEED;desc_hs_configuration;desc_other_speed_config;tud_descriptor_other_speed_configuration_cb
expected_points: TUD_OPT_HIGH_SPEED条件でHS descriptorやother-speed descriptor/callbackが有効化されること、無効時にはFS descriptor中心になることを説明する。
conditional_points: 現在のtarget profileでどの条件がactiveと評価されているか、また静的解析上conditionalなら断定しないこと。
forbidden_claims: HS descriptorが常にビルドされると断定する;TUD_OPT_HIGH_SPEED無効でもother-speed callbackが常に存在すると断定する
evaluation_focus: conditional/supportedの区別、build guardの説明力を見る。

## reminder

最終出力はJSONLのみ。
Markdown、コードフェンス、前置き、後書きは不要です。
