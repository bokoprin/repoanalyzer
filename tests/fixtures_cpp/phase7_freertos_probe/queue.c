#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"

typedef struct QueueDefinition
{
    UBaseType_t uxLength;
} Queue_t;

static void prvCopyDataToQueue( QueueHandle_t xQueue, const void * pvItemToQueue );
static void prvCopyDataFromQueue( QueueHandle_t xQueue, void * pvBuffer );

#if ( configSUPPORT_DYNAMIC_ALLOCATION == 1 )
QueueHandle_t xQueueGenericCreate( UBaseType_t uxQueueLength, UBaseType_t uxItemSize )
{
    static Queue_t xQueue;
    xQueue.uxLength = uxQueueLength;
    ( void ) uxItemSize;
    return &xQueue;
}
#endif

#if ( configSUPPORT_STATIC_ALLOCATION == 1 )
QueueHandle_t xQueueGenericCreateStatic( UBaseType_t uxQueueLength, UBaseType_t uxItemSize, void * pucQueueStorage, void * pxStaticQueue )
{
    static Queue_t xStaticQueue;
    xStaticQueue.uxLength = uxQueueLength;
    ( void ) uxItemSize;
    ( void ) pucQueueStorage;
    ( void ) pxStaticQueue;
    return &xStaticQueue;
}
#endif

BaseType_t xQueueGenericSend( QueueHandle_t xQueue, const void * pvItemToQueue, TickType_t xTicksToWait, BaseType_t xCopyPosition )
{
    configASSERT( xQueue );
    taskENTER_CRITICAL();
    prvCopyDataToQueue( xQueue, pvItemToQueue );
    traceQUEUE_SEND( xQueue );
    xTaskRemoveFromEventList( 0 );
    taskEXIT_CRITICAL();
    portYIELD_WITHIN_API();
    return pdPASS;
}

BaseType_t xQueueGenericSendFromISR( QueueHandle_t xQueue, const void * pvItemToQueue, BaseType_t * pxHigherPriorityTaskWoken, BaseType_t xCopyPosition )
{
    UBaseType_t uxSavedInterruptStatus = portSET_INTERRUPT_MASK_FROM_ISR();
    prvCopyDataToQueue( xQueue, pvItemToQueue );
    portCLEAR_INTERRUPT_MASK_FROM_ISR( uxSavedInterruptStatus );
    portYIELD_FROM_ISR( *pxHigherPriorityTaskWoken );
    return pdPASS;
}

BaseType_t xQueueReceive( QueueHandle_t xQueue, void * pvBuffer, TickType_t xTicksToWait )
{
    vTaskPlaceOnEventList( 0, xTicksToWait );
    prvCopyDataFromQueue( xQueue, pvBuffer );
    return pdPASS;
}

static void prvCopyDataToQueue( QueueHandle_t xQueue, const void * pvItemToQueue )
{
    ( void ) xQueue;
    ( void ) pvItemToQueue;
}

static void prvCopyDataFromQueue( QueueHandle_t xQueue, void * pvBuffer )
{
    ( void ) xQueue;
    ( void ) pvBuffer;
}


QueueHandle_t xQueueCreateMutex( UBaseType_t ucQueueType )
{
    return xQueueGenericCreate( 1, 0 );
}

QueueHandle_t xQueueCreateMutexStatic( UBaseType_t ucQueueType, void * pxStaticQueue )
{
    return xQueueGenericCreateStatic( 1, 0, 0, pxStaticQueue );
}

BaseType_t xQueueGiveMutexRecursive( QueueHandle_t xMutex )
{
    return xQueueGenericSend( xMutex, 0, 0, 0 );
}

BaseType_t xQueueTakeMutexRecursive( QueueHandle_t xMutex, TickType_t xTicksToWait )
{
    return xQueueSemaphoreTake( xMutex, xTicksToWait );
}

QueueHandle_t xQueueCreateCountingSemaphore( UBaseType_t uxMaxCount, UBaseType_t uxInitialCount )
{
    ( void ) uxInitialCount;
    return xQueueGenericCreate( uxMaxCount, 0 );
}

QueueHandle_t xQueueCreateCountingSemaphoreStatic( UBaseType_t uxMaxCount, UBaseType_t uxInitialCount, void * pxStaticQueue )
{
    ( void ) uxInitialCount;
    return xQueueGenericCreateStatic( uxMaxCount, 0, 0, pxStaticQueue );
}

BaseType_t xQueueGiveFromISR( QueueHandle_t xQueue, BaseType_t * pxHigherPriorityTaskWoken )
{
    return xQueueGenericSendFromISR( xQueue, 0, pxHigherPriorityTaskWoken, 0 );
}

BaseType_t xQueueSemaphoreTake( QueueHandle_t xQueue, TickType_t xTicksToWait )
{
    return xQueueReceive( xQueue, 0, xTicksToWait );
}
