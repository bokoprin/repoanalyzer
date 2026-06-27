from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from repoanalyzer.evidence.claims import Claim, ClaimEvidenceBundle, ClaimExtractionBundle, ExtractedClaim
from repoanalyzer.evidence.verify import verify_claims

_SYMBOL = r"`?[A-Za-z_~][A-Za-z0-9_:~]*(?:\([^\)]*\))?`?"
_PATH = r"`?[A-Za-z0-9_./\\\-]+`?"
_LIST_SEP_RE = re.compile(r"\s*(?:,|、|と|\band\b|\bor\b)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class _ClaimPattern:
    pattern_id: str
    claim_type: str
    regex: re.Pattern[str]
    confidence: str = "medium"
    polarity: str = "positive"


_LIST_PATTERNS: list[_ClaimPattern] = [
    _ClaimPattern(
        "ja_calls_list",
        "calls",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?P<objects>{_SYMBOL}(?:\s*(?:と|、|,)\s*{_SYMBOL})+)\s*を\s*(?:呼ぶ|呼び出す|コールする|callする)"),
        "medium",
    ),
    _ClaimPattern(
        "en_calls_list",
        "calls",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:(?:definitely|certainly|always|directly)\s+)?calls\s+(?P<objects>{_SYMBOL}(?:\s*(?:,|\band\b|\bor\b)\s*{_SYMBOL})+)", re.IGNORECASE),
        "medium",
    ),
]

_PATTERNS: list[_ClaimPattern] = [
    _ClaimPattern(
        "ja_calls_negative",
        "calls",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>{_SYMBOL})\s*を\s*(?:呼ばない|呼び出さない|コールしない|callしない)"),
        "medium",
        "negative",
    ),
    _ClaimPattern(
        "en_calls_negative",
        "calls",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:does\s+not|doesn't|do\s+not|don't)\s+calls?\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "medium",
        "negative",
    ),
    _ClaimPattern(
        "ja_reaches_negative",
        "reaches",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*から\s*(?P<object>{_SYMBOL})\s*(?:へ|に)?\s*(?:到達しない|到達できない)"),
        "medium",
        "negative",
    ),
    _ClaimPattern(
        "en_reaches_negative",
        "reaches",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:does\s+not|doesn't|cannot|can't)\s+(?:reach|reaches)\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "medium",
        "negative",
    ),
    _ClaimPattern(
        "ja_definition_negative",
        "definition_exists",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:の)?\s*定義(?:が|は)?\s*(?:存在しない|ない|定義されていない)"),
        "medium",
        "negative",
    ),
    _ClaimPattern(
        "en_definition_negative",
        "definition_exists",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:is|are)\s+not\s+defined", re.IGNORECASE),
        "medium",
        "negative",
    ),
    _ClaimPattern(
        "ja_calls_wo_yobu",
        "calls",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>{_SYMBOL})\s*を\s*(?:呼ぶ|呼び出す|コールする|callする)"),
        "high",
    ),
    _ClaimPattern(
        "en_calls",
        "calls",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:(?:definitely|certainly|always|directly)\s+)?calls\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "ja_reaches_kara",
        "reaches",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*から\s*(?P<object>{_SYMBOL})\s*(?:へ|に)?\s*(?:到達する|到達できる|到達)"),
        "high",
    ),
    _ClaimPattern(
        "en_reaches",
        "reaches",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:eventually\s+)?(?:reaches|can\s+reach)\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "ja_includes_wo",
        "includes",
        re.compile(rf"(?P<subject>{_PATH})\s*(?:は|が)?\s*[\"<]?(?P<object>{_PATH})[\">]?\s*を\s*(?:include|インクルード)する", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "en_includes",
        "includes",
        re.compile(rf"(?P<subject>{_PATH})\s+includes\s+[\"<]?(?P<object>{_PATH})[\">]?", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "ja_execution_context",
        "execution_context",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>ISR|isr|割り込み|task|Task|タスク)\s*(?:コンテキスト|context)?\s*(?:で)?\s*(?:実行される|動く|走る)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_execution_context",
        "execution_context",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:runs|executes|is)\s+in\s+(?P<object>ISR|isr|interrupt|task)\s+(?:context|mode)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_has_execution_context",
        "execution_context",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+has\s+execution_context\s+(?P<object>isr|task)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_callback_registers",
        "callback_registers",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>{_SYMBOL})\s*を\s*(?:コールバック)?登録する"),
        "high",
    ),
    _ClaimPattern(
        "en_callback_registers",
        "callback_registers",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+registers(?:\s+(?:the\s+)?callback)?\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "ja_stores_callback",
        "stores_callback",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>{_SYMBOL})\s*を\s*(?:コールバックとして)?(?:保存する|保持する|格納する)"),
        "high",
    ),
    _ClaimPattern(
        "en_stores_callback",
        "stores_callback",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:stores|saves|keeps)\s+(?:the\s+)?callback\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "ja_invokes_callback",
        "invokes_callback",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>{_SYMBOL})\s*を\s*(?:コールバックとして)?(?:呼び出す|invokeする|実行する)"),
        "high",
    ),
    _ClaimPattern(
        "en_invokes_callback",
        "invokes_callback",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:invokes|calls|executes)\s+(?:the\s+)?callback\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "ja_callback_dataflow",
        "callback_dataflow",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*に渡された\s*(?P<callback>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>{_SYMBOL})\s*で\s*(?:callback|コールバックとして)?(?:呼び出される|実行される)"),
        "high",
    ),
    _ClaimPattern(
        "en_callback_dataflow",
        "callback_dataflow",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:dataflows|flows|passes)\s+(?:the\s+)?callback\s+(?P<callback>{_SYMBOL})\s+to\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "ja_task_entry_dataflow",
        "task_entry_dataflow",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:に渡された)?\s*(?P<entry>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>{_SYMBOL})\s*(?:へ|に)?\s*(?:task entry|タスクエントリ|タスク関数)(?:として)?(?:渡る|流れる|登録される)", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "en_task_entry_dataflow",
        "task_entry_dataflow",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:dataflows|flows|passes|registers)\s+(?:the\s+)?task\s+entry\s+(?P<entry>{_SYMBOL})\s+to\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "en_scheduler_enters_critical",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:enters|enters\s+the|enter)\s+(?:a\s+)?critical\s+section", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_scheduler_exits_critical",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:exits|exits\s+the|exit)\s+(?:a\s+)?critical\s+section", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_scheduler_suspends",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:suspends|suspend)\s+(?:the\s+)?scheduler", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_scheduler_resumes",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:resumes|resume)\s+(?:the\s+)?scheduler", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_scheduler_requests_context_switch",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:requests|request)\s+(?:a\s+)?context\s+switch", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_scheduler_masks_interrupts_from_isr",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:masks|sets)\s+(?:the\s+)?interrupt\s+mask(?:\s+from\s+ISR)?", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_scheduler_clears_interrupt_mask_from_isr",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:clears|restores)\s+(?:the\s+)?interrupt\s+mask(?:\s+from\s+ISR)?", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_scheduler_enters_critical",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?:critical section|クリティカルセクション)\s*(?:に)?\s*(?:入る|入れる)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_scheduler_requests_context_switch",
        "scheduler_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?:context switch|コンテキストスイッチ)\s*(?:を)?\s*(?:要求する|リクエストする)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_task_state_moves_ready",
        "task_state_transition",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:moves|adds|places)\s+(?:a\s+)?task\s+to\s+(?:the\s+)?ready\s+list", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_task_state_moves_delayed",
        "task_state_transition",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:moves|adds|places)\s+(?:the\s+)?(?:current\s+)?task\s+to\s+(?:the\s+)?delayed\s+list", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_task_state_blocks_event",
        "task_state_transition",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:blocks|places)\s+(?:a\s+)?task\s+on\s+(?:an\s+)?event\s+list", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_task_state_unblocks_event",
        "task_state_transition",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:unblocks|removes)\s+(?:a\s+)?task\s+from\s+(?:an\s+)?event\s+list", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_task_state_removes_list",
        "task_state_transition",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+removes\s+(?:a\s+)?task\s+from\s+(?:a\s+)?list", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_task_state_moves_ready",
        "task_state_transition",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?:タスク|task)\s*(?:を)?\s*(?:ready\s*list|レディリスト|Readyリスト)\s*(?:へ|に)?\s*(?:移す|追加する|入れる)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_task_state_blocks_event",
        "task_state_transition",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?:タスク|task)\s*(?:を)?\s*(?:event\s*list|イベントリスト|待ちリスト)\s*(?:で|に)?\s*(?:ブロックする|待たせる|追加する)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_stream_send",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:sends|writes)\s+(?:to\s+)?(?:a\s+)?stream\s+buffer", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_stream_receive",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:receives|reads)\s+(?:from\s+)?(?:a\s+)?stream\s+buffer", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_message_send",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:sends|writes)\s+(?:to\s+)?(?:a\s+)?message\s+buffer", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_message_receive",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:receives|reads)\s+(?:from\s+)?(?:a\s+)?message\s+buffer", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_event_set",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:sets|sets\s+the)\s+(?:event\s+)?bits", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_event_clear",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:clears|clears\s+the)\s+(?:event\s+)?bits", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_event_wait",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:waits|blocks)\s+for\s+(?:event\s+)?bits", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_event_sync",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:syncs|synchronizes)\s+(?:event\s+)?bits", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_notify_task",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:notifies\s+task|sends\s+(?:a\s+)?task(?:\s+notification)?|notifies\s+(?:a\s+)?task(?:\s+notification)?)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_wait_notification",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+waits\s+for\s+(?:a\s+)?task\s+notification", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_gives_semaphore",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:gives|releases)\s+(?:a\s+)?semaphore", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_takes_semaphore",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:takes|waits\s+on|acquires)\s+(?:a\s+)?semaphore", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_creates_semaphore",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:creates|initializes)\s+(?:a\s+)?semaphore", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_gives_mutex",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:gives|releases)\s+(?:a\s+)?mutex", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_takes_mutex",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:takes|acquires|locks)\s+(?:a\s+)?mutex", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_kernel_creates_mutex",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:creates|initializes)\s+(?:a\s+)?mutex", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_kernel_event_set",
        "kernel_object_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?:イベントビット|event\s*bits)\s*(?:を)?\s*(?:セットする|設定する)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_hook_invokes_trace",
        "hook_assert_trace_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:invokes|calls|emits|uses)\s+(?:FreeRTOS\s+)?trace\s+hook(?:\s+(?P<object>{_SYMBOL}))?", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_hook_invokes_assert",
        "hook_assert_trace_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:invokes|calls|uses|checks)\s+(?:the\s+)?(?:assert\s+handler|configASSERT)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_hook_invokes_application_hook",
        "hook_assert_trace_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:invokes|calls|uses)\s+(?:an\s+)?application\s+hook(?:\s+(?P<object>{_SYMBOL}))?", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_hook_coverage_marker",
        "hook_assert_trace_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:hits|reaches|uses|marks)\s+(?:a\s+)?coverage\s+marker", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_hook_invokes_trace",
        "hook_assert_trace_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?:trace\s*hook|トレースフック)\s*(?:を)?\s*(?:呼ぶ|呼び出す|使う)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_heap_allocates",
        "heap_allocator_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:allocates|allocates\s+from|provides)\s+(?:FreeRTOS\s+)?heap\s+memory", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_heap_frees",
        "heap_allocator_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:frees|releases)\s+(?:FreeRTOS\s+)?heap\s+memory", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_heap_coalesces",
        "heap_allocator_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:coalesces|merges)\s+(?:free\s+)?blocks", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_heap_uses_libc",
        "heap_allocator_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|delegates\s+to)\s+(?:the\s+)?libc\s+allocator", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_heap_multiple_regions",
        "heap_allocator_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|supports|defines)\s+multiple\s+heap\s+regions", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_heap_no_free",
        "heap_allocator_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:does\s+not\s+support|doesn't\s+support|has\s+no)\s+free", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_smp_scheduler",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|has|coordinates)\s+(?:the\s+)?SMP\s+scheduler", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_core_affinity",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|sets|has|preserves)\s+core\s+affinity", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_cross_core_yield",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|requests|performs)\s+(?:a\s+)?cross-core\s+yield", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_smp_locking",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|takes|releases)\s+SMP\s+locking", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_mpu_wrappers",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|has|goes\s+through)\s+(?:FreeRTOS\s+)?MPU\s+wrappers?", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_mpu_regions",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:configures|sets|updates)\s+MPU\s+regions?", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_mpu_access",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:checks|validates|authorizes)\s+MPU\s+access", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_privilege",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:crosses|uses|enters)\s+(?:a\s+)?privilege\s+boundary", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_assembly",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|reaches|crosses)\s+port\s+assembly", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_adv_secure_context",
        "port_advanced_semantic",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:uses|reaches|crosses)\s+(?:a\s+)?secure\s+context\s+boundary", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_boundary_crosses",
        "port_boundary",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:crosses|reaches)\s+(?:a\s+)?(?:FreeRTOS\s+)?port\s+boundary\s+(?:to|at|via)\s+(?P<object>{_SYMBOL})", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_port_boundary_has",
        "port_boundary",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:has|is|marks)\s+(?:a\s+)?(?:FreeRTOS\s+)?port\s+boundary", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_port_boundary_crosses",
        "port_boundary",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?P<object>{_SYMBOL})\s*(?:で|へ|に|を介して)?\s*(?:port\s*boundary|ポート境界|port層|ポート層)\s*(?:を)?\s*(?:越える|到達する|またぐ)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_port_boundary_has",
        "port_boundary",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?:port\s*boundary|ポート境界|port層|ポート層)(?:である|になる|を持つ)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_definition_exists",
        "definition_exists",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:の)?\s*定義(?:が|は)?\s*(?:存在する|ある|定義されている)"),
        "high",
    ),
    _ClaimPattern(
        "en_definition_exists_prefix",
        "definition_exists",
        re.compile(rf"(?:definition\s+exists\s+for|defines)\s+(?P<subject>{_SYMBOL})", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "en_definition_exists_suffix",
        "definition_exists",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:is|are)\s+defined", re.IGNORECASE),
        "high",
    ),
    _ClaimPattern(
        "en_target_profile_name",
        "target_profile",
        re.compile(r"(?:target\s+profile|profile)\s+(?:is|equals|=)\s+(?P<object>[A-Za-z0-9_./\\\-]+)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_target_profile_attribute",
        "target_profile",
        re.compile(r"(?P<subject>active_port|heap|compile_commands|config_header|active_path_prefix|inactive_path_prefix)\s+(?:is|equals|=)\s+(?P<object>[A-Za-z0-9_./\\\-]+)\s+(?:in\s+the\s+target\s+profile|for\s+the\s+target\s+profile)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_target_profile_name",
        "target_profile",
        re.compile(r"(?:target\s+profile|ターゲットプロファイル|対象プロファイル)\s*(?:は|が|=)\s*(?P<object>[A-Za-z0-9_./\\\-]+)"),
        "medium",
    ),
    _ClaimPattern(
        "ja_target_profile_attribute",
        "target_profile",
        re.compile(r"(?P<subject>active_port|heap|compile_commands|config_header|active_path_prefix|inactive_path_prefix)\s*(?:は|が|=)\s*(?P<object>[A-Za-z0-9_./\\\-]+)\s*(?:ターゲットプロファイル|対象プロファイル)(?:内|で)?"),
        "medium",
    ),
    _ClaimPattern(
        "en_allocation_profile",
        "allocation_profile",
        re.compile(r"(?P<subject>dynamic|static)\s+allocation\s+(?:is\s+)?(?P<object>enabled|disabled|on|off)\s+(?:in\s+the\s+target\s+profile|in\s+the\s+target\s+build|for\s+the\s+target\s+profile)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_allocation_profile",
        "allocation_profile",
        re.compile(r"(?P<subject>dynamic|static|動的|静的)\s*(?:allocation|アロケーション|確保)?\s*(?:は|が)?\s*(?P<object>enabled|disabled|有効|無効)\s*(?:対象プロファイル|ターゲットプロファイル|対象ビルド)(?:で|内で)?", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_build_config_value",
        "build_config",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*(?:対象ビルドで)?\s*(?:値)?\s*(?P<object>[A-Za-z0-9_]+)\s*(?:である|に設定されている|equals?)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_build_config_value",
        "build_config",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:is|equals|has\s+value)\s+(?P<object>[A-Za-z0-9_]+)\s+(?:in\s+the\s+target\s+build|in\s+the\s+build|for\s+the\s+target\s+profile)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_build_active",
        "build_active",
        re.compile(rf"(?P<subject>{_SYMBOL})\s*(?:は|が)?\s*対象ビルドで\s*(?:有効|active)"),
        "medium",
    ),
    _ClaimPattern(
        "en_build_active",
        "build_active",
        re.compile(rf"(?P<subject>{_SYMBOL})\s+(?:is\s+)?(?:active\s+in\s+the\s+target\s+build|build\s+active|target-build\s+active)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "ja_file_active",
        "file_active",
        re.compile(rf"(?P<subject>{_PATH})\s*(?:は|が)?\s*(?:target\s+profile|ターゲットプロファイル|対象プロファイル|対象ビルド)\s*(?:で|内で)?\s*(?P<object>active|inactive|有効|無効)", re.IGNORECASE),
        "medium",
    ),
    _ClaimPattern(
        "en_file_active",
        "file_active",
        re.compile(rf"(?P<subject>{_PATH})\s+(?:is\s+)?(?P<object>active|inactive)\s+(?:in\s+the\s+target\s+profile|in\s+the\s+target\s+build|for\s+the\s+target\s+profile)", re.IGNORECASE),
        "medium",
    ),
]


# Retained for warning-only cases that are syntactically negated but not supported by a negative pattern.
_NEGATION_RE = re.compile(r"(?:does\s+not|doesn't|not\s+call|呼ばない|呼び出さない|登録しない|到達しない)", re.IGNORECASE)


def extract_claims(text: str) -> ClaimExtractionBundle:
    extracted: list[ExtractedClaim] = []
    warnings: list[dict[str, object]] = []
    occupied: list[range] = []

    for item in _extract_list_claims(text, occupied):
        extracted.append(item)
        occupied.append(range(item.span_start, item.span_end))

    for pattern in _PATTERNS:
        for match in pattern.regex.finditer(text):
            span = range(match.start(), match.end())
            if _overlaps(span, occupied):
                continue
            snippet = text[match.start():match.end()]
            if pattern.polarity == "positive" and _NEGATION_RE.search(snippet):
                warnings.append({
                    "warning_type": "negated_claim_not_extracted",
                    "message": "A negated natural-language claim matched only a positive pattern and was not extracted.",
                    "text": snippet,
                    "span": [match.start(), match.end()],
                })
                occupied.append(span)
                continue
            claim = _claim_from_match(pattern, match, text)
            if claim is None:
                continue
            extracted.append(
                ExtractedClaim(
                    claim=claim,
                    text=snippet,
                    span_start=match.start(),
                    span_end=match.end(),
                    pattern_id=pattern.pattern_id,
                    confidence=pattern.confidence,
                )
            )
            occupied.append(span)
    extracted.sort(key=lambda item: (item.span_start, item.span_end, item.pattern_id))
    if not extracted:
        warnings.append({
            "warning_type": "no_supported_claim_patterns",
            "message": "No supported deterministic claim pattern was found.",
        })
    return ClaimExtractionBundle(text=text, extracted_claims=extracted, warnings=warnings)


def verify_claim_text(repo: str | Path, text: str) -> ClaimEvidenceBundle:
    extraction = extract_claims(text)
    if not extraction.extracted_claims:
        return ClaimEvidenceBundle(
            verdicts=[],
            extracted_claims=[],
            extraction_warnings=extraction.warnings,
        )
    bundle = verify_claims(repo, [item.claim for item in extraction.extracted_claims])
    return ClaimEvidenceBundle(
        verdicts=bundle.verdicts,
        extracted_claims=extraction.extracted_claims,
        extraction_warnings=extraction.warnings,
    )


def _extract_list_claims(text: str, occupied: Iterable[range]) -> list[ExtractedClaim]:
    out: list[ExtractedClaim] = []
    for pattern in _LIST_PATTERNS:
        for match in pattern.regex.finditer(text):
            span = range(match.start(), match.end())
            if _overlaps(span, occupied):
                continue
            subject = _clean_endpoint(match.group("subject"))
            objects = [_clean_endpoint(part) for part in _LIST_SEP_RE.split(match.group("objects"))]
            objects = [obj for obj in objects if obj]
            if not subject or len(objects) < 2:
                continue
            snippet = text[match.start():match.end()]
            for obj in objects:
                claim = Claim(
                    pattern.claim_type,
                    subject=subject,
                    object=obj,
                    payload={
                        "extraction": {
                            "source": "deterministic_natural_language_list_pattern",
                            "pattern_id": pattern.pattern_id,
                            "span": [match.start(), match.end()],
                            "text": snippet,
                            "list_item": obj,
                        }
                    },
                )
                out.append(
                    ExtractedClaim(
                        claim=claim,
                        text=snippet,
                        span_start=match.start(),
                        span_end=match.end(),
                        pattern_id=pattern.pattern_id,
                        confidence=pattern.confidence,
                    )
                )
    return out


def _overlaps(span: range, occupied: Iterable[range]) -> bool:
    return any(span.start < other.stop and other.start < span.stop for other in occupied)


def _claim_from_match(pattern: _ClaimPattern, match: re.Match[str], text: str) -> Claim | None:
    subject = _clean_endpoint(match.groupdict().get("subject"))
    obj = _clean_endpoint(match.groupdict().get("object"))
    payload = {
        "extraction": {
            "source": "deterministic_natural_language_pattern",
            "pattern_id": pattern.pattern_id,
            "span": [match.start(), match.end()],
            "text": text[match.start():match.end()],
            "polarity": pattern.polarity,
        }
    }
    if pattern.polarity == "negative":
        payload["polarity"] = "negative"
    if pattern.claim_type in {"calls", "reaches", "includes", "callback_registers", "stores_callback", "invokes_callback"}:
        if not subject or not obj:
            return None
        return Claim(pattern.claim_type, subject=subject, object=obj, payload=payload)
    if pattern.claim_type == "execution_context":
        if not subject or not obj:
            return None
        normalized = {"割り込み": "isr", "interrupt": "isr", "ISR": "isr", "isr": "isr", "task": "task", "Task": "task", "タスク": "task"}.get(obj, obj.lower())
        return Claim(pattern.claim_type, subject=subject, object=normalized, payload=payload)
    if pattern.claim_type == "callback_dataflow":
        callback = _clean_endpoint(match.groupdict().get("callback"))
        if not subject or not obj:
            return None
        if callback:
            payload["callback_symbol"] = callback
        return Claim(pattern.claim_type, subject=subject, object=obj, payload=payload)
    if pattern.claim_type == "task_entry_dataflow":
        entry = _clean_endpoint(match.groupdict().get("entry"))
        if not subject or not obj:
            return None
        if entry:
            payload["task_entry_symbol"] = entry
        return Claim(pattern.claim_type, subject=subject, object=obj, payload=payload)
    if pattern.claim_type == "scheduler_semantic":
        if not subject:
            return None
        semantic_by_pattern = {
            "en_scheduler_enters_critical": "enters_critical_section",
            "en_scheduler_exits_critical": "exits_critical_section",
            "en_scheduler_suspends": "suspends_scheduler",
            "en_scheduler_resumes": "resumes_scheduler",
            "en_scheduler_requests_context_switch": "requests_context_switch",
            "en_scheduler_masks_interrupts_from_isr": "masks_interrupts_from_isr",
            "en_scheduler_clears_interrupt_mask_from_isr": "clears_interrupt_mask_from_isr",
            "ja_scheduler_enters_critical": "enters_critical_section",
            "ja_scheduler_requests_context_switch": "requests_context_switch",
        }
        semantic = semantic_by_pattern.get(pattern.pattern_id)
        return Claim(pattern.claim_type, subject=subject, object=semantic, payload=payload)
    if pattern.claim_type == "kernel_object_semantic":
        if not subject:
            return None
        semantic_by_pattern = {
            "en_kernel_stream_send": "sends_to_stream_buffer",
            "en_kernel_stream_receive": "receives_from_stream_buffer",
            "en_kernel_message_send": "sends_to_message_buffer",
            "en_kernel_message_receive": "receives_from_message_buffer",
            "en_kernel_event_set": "sets_event_bits",
            "en_kernel_event_clear": "clears_event_bits",
            "en_kernel_event_wait": "waits_for_event_bits",
            "en_kernel_event_sync": "syncs_event_bits",
            "en_kernel_notify_task": "notifies_task",
            "en_kernel_wait_notification": "waits_for_task_notification",
            "en_kernel_gives_semaphore": "gives_semaphore",
            "en_kernel_takes_semaphore": "takes_semaphore",
            "en_kernel_creates_semaphore": "creates_semaphore",
            "en_kernel_gives_mutex": "gives_mutex",
            "en_kernel_takes_mutex": "takes_mutex",
            "en_kernel_creates_mutex": "creates_mutex",
            "ja_kernel_event_set": "sets_event_bits",
        }
        semantic = semantic_by_pattern.get(pattern.pattern_id, obj)
        return Claim(pattern.claim_type, subject=subject, object=semantic, payload=payload)
    if pattern.claim_type == "hook_assert_trace_semantic":
        if not subject:
            return None
        semantic_by_pattern = {
            "en_hook_invokes_trace": "invokes_trace_hook",
            "en_hook_invokes_assert": "invokes_assert_handler",
            "en_hook_invokes_application_hook": "invokes_application_hook",
            "en_hook_coverage_marker": "coverage_marker",
            "ja_hook_invokes_trace": "invokes_trace_hook",
        }
        semantic = semantic_by_pattern.get(pattern.pattern_id, obj)
        if obj:
            payload = {**payload, "api_name": obj}
        return Claim(pattern.claim_type, subject=subject, object=semantic, payload=payload)
    if pattern.claim_type == "heap_allocator_semantic":
        if not subject:
            return None
        semantic_by_pattern = {
            "en_heap_allocates": "allocates_heap_memory",
            "en_heap_frees": "frees_heap_memory",
            "en_heap_coalesces": "coalesces_free_blocks",
            "en_heap_uses_libc": "uses_libc_allocator",
            "en_heap_multiple_regions": "uses_multiple_heap_regions",
            "en_heap_no_free": "does_not_support_free",
        }
        semantic = semantic_by_pattern.get(pattern.pattern_id, obj)
        return Claim(pattern.claim_type, subject=subject, object=semantic, payload=payload)
    if pattern.claim_type == "port_advanced_semantic":
        if not subject:
            return None
        semantic_by_pattern = {
            "en_port_adv_smp_scheduler": "uses_smp_scheduler",
            "en_port_adv_core_affinity": "uses_core_affinity",
            "en_port_adv_cross_core_yield": "uses_cross_core_yield",
            "en_port_adv_smp_locking": "uses_smp_locking",
            "en_port_adv_mpu_wrappers": "uses_mpu_wrappers",
            "en_port_adv_mpu_regions": "configures_mpu_regions",
            "en_port_adv_mpu_access": "checks_mpu_access",
            "en_port_adv_privilege": "crosses_privilege_boundary",
            "en_port_adv_assembly": "uses_port_assembly",
            "en_port_adv_secure_context": "uses_secure_context_boundary",
        }
        semantic = semantic_by_pattern.get(pattern.pattern_id, obj)
        return Claim(pattern.claim_type, subject=subject, object=semantic, payload=payload)

    if pattern.claim_type == "port_boundary":
        if not subject:
            return None
        return Claim(pattern.claim_type, subject=subject, object=obj or "port_layer", payload=payload)
    if pattern.claim_type == "task_state_transition":
        if not subject:
            return None
        transition_by_pattern = {
            "en_task_state_moves_ready": "moves_task_to_ready_list",
            "en_task_state_moves_delayed": "moves_task_to_delayed_list",
            "en_task_state_blocks_event": "blocks_task_on_event_list",
            "en_task_state_unblocks_event": "unblocks_task_from_event_list",
            "en_task_state_removes_list": "removes_task_from_list",
            "ja_task_state_moves_ready": "moves_task_to_ready_list",
            "ja_task_state_blocks_event": "blocks_task_on_event_list",
        }
        transition = transition_by_pattern.get(pattern.pattern_id, obj)
        return Claim(pattern.claim_type, subject=subject, object=transition, payload=payload)
    if pattern.claim_type == "allocation_profile":
        if not subject or not obj:
            return None
        mode = {"動的": "dynamic", "静的": "static"}.get(subject, subject.lower())
        state = {"有効": "enabled", "無効": "disabled"}.get(obj, obj.lower())
        return Claim(pattern.claim_type, subject=mode, object=state, payload=payload)
    if pattern.claim_type == "build_config":
        if not subject:
            return None
        # Avoid stealing build-active/file-active prose such as
        # ``xTimerCreateTimerTask is active in the target build``.  Those are
        # target-build status claims, not macro value claims.
        if (obj or "").lower() in {"active", "inactive"}:
            return None
        return Claim(pattern.claim_type, subject=subject, object=obj, payload=payload)
    if pattern.claim_type == "target_profile":
        if subject:
            return Claim(pattern.claim_type, subject=subject, object=obj, payload=payload)
        if obj:
            return Claim(pattern.claim_type, subject="name", object=obj, payload=payload)
        return None
    if pattern.claim_type == "file_active":
        if not subject:
            return None
        normalized = {"有効": "active", "無効": "inactive"}.get(obj or "", (obj or "active").lower())
        return Claim(pattern.claim_type, subject=subject, object=normalized, payload=payload)
    if pattern.claim_type in {"definition_exists", "build_active"}:
        if not subject:
            return None
        return Claim(pattern.claim_type, subject=subject, payload=payload)
    return None


def _clean_endpoint(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip("` ")
    cleaned = cleaned.strip("。、,.，;；:：()[]{}")
    cleaned = cleaned.strip('"\'<>')
    if cleaned.endswith("()"):
        cleaned = cleaned[:-2]
    return cleaned or None
