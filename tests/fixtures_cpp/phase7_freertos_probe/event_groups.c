#include "FreeRTOS.h"
#include "event_groups.h"

EventBits_t xEventGroupSetBits( EventGroupHandle_t xEventGroup, EventBits_t uxBitsToSet )
{
    ( void ) xEventGroup;
    return uxBitsToSet;
}

EventBits_t xEventGroupClearBits( EventGroupHandle_t xEventGroup, EventBits_t uxBitsToClear )
{
    ( void ) xEventGroup;
    return uxBitsToClear;
}

EventBits_t xEventGroupWaitBits( EventGroupHandle_t xEventGroup, EventBits_t uxBitsToWaitFor, BaseType_t xClearOnExit, BaseType_t xWaitForAllBits, TickType_t xTicksToWait )
{
    ( void ) xEventGroup;
    ( void ) xClearOnExit;
    ( void ) xWaitForAllBits;
    ( void ) xTicksToWait;
    return uxBitsToWaitFor;
}

EventBits_t xEventGroupSync( EventGroupHandle_t xEventGroup, EventBits_t uxBitsToSet, EventBits_t uxBitsToWaitFor, TickType_t xTicksToWait )
{
    xEventGroupSetBits( xEventGroup, uxBitsToSet );
    return xEventGroupWaitBits( xEventGroup, uxBitsToWaitFor, pdTRUE, pdTRUE, xTicksToWait );
}
