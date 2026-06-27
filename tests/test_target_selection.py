from repoanalyzer.core.target_selection import decide_target_file, filter_active_files


class _Source:
    def __init__(self, path: str) -> None:
        self.path = path


def _profile():
    return {
        "name": "freertos-gcc-arm-cm4f-heap4",
        "active_path_prefixes": ["tasks.c", "include", "portable"],
        "active_port": "portable/GCC/ARM_CM4F",
        "heap": "heap_4",
    }


def test_target_selection_marks_active_port_and_heap() -> None:
    profile = _profile()
    source_files = {"tasks.c", "portable/GCC/ARM_CM4F/port.c", "portable/MemMang/heap_4.c"}

    port = decide_target_file("portable/GCC/ARM_CM4F/port.c", source_files, profile)
    heap = decide_target_file("portable/MemMang/heap_4.c", source_files, profile)

    assert port.status == "active"
    assert "active_port" in port.reasons
    assert heap.status == "active"
    assert "selected_heap" in heap.reasons


def test_target_selection_marks_non_selected_port_and_heap_inactive() -> None:
    profile = _profile()
    source_files = {"tasks.c", "portable/GCC/ARM_CM4F/port.c", "portable/MemMang/heap_4.c"}

    other_port = decide_target_file("portable/GCC/ARM_CM3/port.c", source_files, profile)
    other_heap = decide_target_file("portable/MemMang/heap_3.c", source_files, profile)
    active = filter_active_files([
        _Source("tasks.c"),
        _Source("portable/GCC/ARM_CM4F/port.c"),
        _Source("portable/GCC/ARM_CM3/port.c"),
        _Source("portable/MemMang/heap_4.c"),
        _Source("portable/MemMang/heap_3.c"),
    ], sorted(source_files), profile)

    assert other_port.status == "inactive"
    assert other_port.reasons == ["non_selected_port"]
    assert other_heap.status == "inactive"
    assert other_heap.reasons == ["non_selected_heap"]
    assert [item.path for item in active] == ["tasks.c", "portable/GCC/ARM_CM4F/port.c", "portable/MemMang/heap_4.c"]


def test_target_selection_marks_tinyusb_src_portable_controller_port() -> None:
    profile = {
        "name": "tinyusb-device-cdc-msc-stm32f407disco-none",
        "active_path_prefixes": ["src"],
        "active_port": "src/portable/synopsys/dwc2",
    }
    source_files = {"src/portable/synopsys/dwc2/dcd_dwc2.c"}

    selected = decide_target_file("src/portable/synopsys/dwc2/dcd_dwc2.c", source_files, profile)
    non_selected = decide_target_file("src/portable/st/stm32_fsdev/dcd_stm32_fsdev.c", source_files, profile)

    assert selected.status == "active"
    assert "active_port" in selected.reasons
    assert non_selected.status == "inactive"
    assert non_selected.reasons == ["non_selected_port"]
