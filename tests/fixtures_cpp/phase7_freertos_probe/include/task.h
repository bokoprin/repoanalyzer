#ifndef TASK_H
#define TASK_H
#include "FreeRTOS.h"
BaseType_t xTaskCreate( TaskFunction_t pxTaskCode, const char * pcName, unsigned short usStackDepth, void * pvParameters, UBaseType_t uxPriority, TaskHandle_t * pxCreatedTask );
TaskHandle_t xTaskCreateStatic( TaskFunction_t pxTaskCode, const char * pcName, unsigned short usStackDepth, void * pvParameters, UBaseType_t uxPriority, void * puxStackBuffer, void * pxTaskBuffer );
void vTaskStartScheduler( void );
BaseType_t xTaskIncrementTick( void );
void vTaskSuspendAll( void );
BaseType_t xTaskResumeAll( void );
void vTaskPlaceOnEventList( List_t * pxEventList, TickType_t xTicksToWait );
BaseType_t xTaskRemoveFromEventList( const List_t * pxEventList );
BaseType_t xTaskGenericNotify( TaskHandle_t xTaskToNotify, UBaseType_t uxIndexToNotify, uint32_t ulValue, UBaseType_t eAction, uint32_t * pulPreviousNotificationValue );
BaseType_t xTaskGenericNotifyFromISR( TaskHandle_t xTaskToNotify, UBaseType_t uxIndexToNotify, uint32_t ulValue, UBaseType_t eAction, uint32_t * pulPreviousNotificationValue, BaseType_t * pxHigherPriorityTaskWoken );
BaseType_t xTaskGenericNotifyWait( UBaseType_t uxIndexToWaitOn, uint32_t ulBitsToClearOnEntry, uint32_t ulBitsToClearOnExit, uint32_t * pulNotificationValue, TickType_t xTicksToWait );
uint32_t ulTaskGenericNotifyTake( UBaseType_t uxIndexToWaitOn, BaseType_t xClearCountOnExit, TickType_t xTicksToWait );
#endif
