#ifndef EVENT_GROUPS_H
#define EVENT_GROUPS_H
#include "FreeRTOS.h"
EventBits_t xEventGroupSetBits( EventGroupHandle_t xEventGroup, EventBits_t uxBitsToSet );
EventBits_t xEventGroupClearBits( EventGroupHandle_t xEventGroup, EventBits_t uxBitsToClear );
EventBits_t xEventGroupWaitBits( EventGroupHandle_t xEventGroup, EventBits_t uxBitsToWaitFor, BaseType_t xClearOnExit, BaseType_t xWaitForAllBits, TickType_t xTicksToWait );
EventBits_t xEventGroupSync( EventGroupHandle_t xEventGroup, EventBits_t uxBitsToSet, EventBits_t uxBitsToWaitFor, TickType_t xTicksToWait );
#endif
