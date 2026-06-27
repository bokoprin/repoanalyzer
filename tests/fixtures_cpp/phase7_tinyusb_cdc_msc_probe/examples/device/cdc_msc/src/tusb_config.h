#ifndef TUSB_CONFIG_H_
#define TUSB_CONFIG_H_

#ifndef BOARD_TUD_RHPORT
#define BOARD_TUD_RHPORT      0
#endif

#ifndef BOARD_TUD_MAX_SPEED
#define BOARD_TUD_MAX_SPEED   OPT_MODE_FULL_SPEED
#endif

#ifndef CFG_TUSB_MCU
#define CFG_TUSB_MCU          OPT_MCU_STM32F4
#endif

#ifndef CFG_TUSB_OS
#define CFG_TUSB_OS           OPT_OS_NONE
#endif

#define CFG_TUD_ENABLED       1
#define CFG_TUD_MAX_SPEED     BOARD_TUD_MAX_SPEED
#define CFG_TUD_ENDPOINT0_SIZE 64
#define CFG_TUD_INTERFACE_MAX  4
#define CFG_TUD_ENDPOINT_MAX   8

#define CFG_TUD_CDC           1
#define CFG_TUD_MSC           1
#define CFG_TUD_HID           0
#define CFG_TUD_MIDI          0
#define CFG_TUD_VENDOR        0

#endif
