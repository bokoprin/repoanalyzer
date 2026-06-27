#ifndef QUEUE_H
#define QUEUE_H
#include "FreeRTOS.h"
QueueHandle_t xQueueGenericCreate( UBaseType_t uxQueueLength, UBaseType_t uxItemSize );
QueueHandle_t xQueueGenericCreateStatic( UBaseType_t uxQueueLength, UBaseType_t uxItemSize, void * pucQueueStorage, void * pxStaticQueue );
BaseType_t xQueueGenericSend( QueueHandle_t xQueue, const void * pvItemToQueue, TickType_t xTicksToWait, BaseType_t xCopyPosition );
BaseType_t xQueueGenericSendFromISR( QueueHandle_t xQueue, const void * pvItemToQueue, BaseType_t * pxHigherPriorityTaskWoken, BaseType_t xCopyPosition );
BaseType_t xQueueReceive( QueueHandle_t xQueue, void * pvBuffer, TickType_t xTicksToWait );
QueueHandle_t xQueueCreateMutex( UBaseType_t ucQueueType );
QueueHandle_t xQueueCreateMutexStatic( UBaseType_t ucQueueType, void * pxStaticQueue );
BaseType_t xQueueGiveMutexRecursive( QueueHandle_t xMutex );
BaseType_t xQueueTakeMutexRecursive( QueueHandle_t xMutex, TickType_t xTicksToWait );
QueueHandle_t xQueueCreateCountingSemaphore( UBaseType_t uxMaxCount, UBaseType_t uxInitialCount );
QueueHandle_t xQueueCreateCountingSemaphoreStatic( UBaseType_t uxMaxCount, UBaseType_t uxInitialCount, void * pxStaticQueue );
BaseType_t xQueueGiveFromISR( QueueHandle_t xQueue, BaseType_t * pxHigherPriorityTaskWoken );
BaseType_t xQueueSemaphoreTake( QueueHandle_t xQueue, TickType_t xTicksToWait );
#endif
