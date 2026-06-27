#include "FreeRTOS.h"
#include "task.h"
#include "timers.h"
#include "portable/GCC/ARM_CM4F/portmacro.h"

typedef struct tskTaskControlBlock
{
    TaskFunction_t pxTaskCode;
    void * pxTopOfStack;
} TCB_t;

static TCB_t * prvCreateTask( TaskFunction_t pxTaskCode, const char * pcName, unsigned short usStackDepth, void * pvParameters, UBaseType_t uxPriority, TaskHandle_t * pxCreatedTask );
static void prvInitialiseNewTask( TaskFunction_t pxTaskCode, void * pvParameters, TCB_t * pxNewTCB );
static void prvAddNewTaskToReadyList( TCB_t * pxNewTCB );
static void prvAddCurrentTaskToDelayedList( TickType_t xTicksToWait, BaseType_t xCanBlockIndefinitely );
void vListInsert( List_t * pxList, ListItem_t * pxNewListItem );
void vListInsertEnd( List_t * pxList, ListItem_t * pxNewListItem );
UBaseType_t uxListRemove( ListItem_t * pxItemToRemove );
#define prvAddTaskToReadyList( pxTCB ) vListInsertEnd( 0, 0 )

#if ( configSUPPORT_DYNAMIC_ALLOCATION == 1 )
BaseType_t xTaskCreate( TaskFunction_t pxTaskCode, const char * pcName, unsigned short usStackDepth, void * pvParameters, UBaseType_t uxPriority, TaskHandle_t * pxCreatedTask )
{
    configASSERT( pxTaskCode );
    TCB_t * pxNewTCB = prvCreateTask( pxTaskCode, pcName, usStackDepth, pvParameters, uxPriority, pxCreatedTask );
    traceTASK_CREATE( pxNewTCB );
    prvAddNewTaskToReadyList( pxNewTCB );
    return pdPASS;
}
#endif

#if ( configSUPPORT_STATIC_ALLOCATION == 1 )
TaskHandle_t xTaskCreateStatic( TaskFunction_t pxTaskCode, const char * pcName, unsigned short usStackDepth, void * pvParameters, UBaseType_t uxPriority, void * puxStackBuffer, void * pxTaskBuffer )
{
    static TCB_t xStaticTCB;
    ( void ) pcName;
    ( void ) usStackDepth;
    ( void ) uxPriority;
    ( void ) puxStackBuffer;
    ( void ) pxTaskBuffer;
    prvInitialiseNewTask( pxTaskCode, pvParameters, &xStaticTCB );
    prvAddNewTaskToReadyList( &xStaticTCB );
    return &xStaticTCB;
}
#endif

static TCB_t * prvCreateTask( TaskFunction_t pxTaskCode, const char * pcName, unsigned short usStackDepth, void * pvParameters, UBaseType_t uxPriority, TaskHandle_t * pxCreatedTask )
{
    static TCB_t xTCB;
    prvInitialiseNewTask( pxTaskCode, pvParameters, &xTCB );
    return &xTCB;
}

static void prvInitialiseNewTask( TaskFunction_t pxTaskCode, void * pvParameters, TCB_t * pxNewTCB )
{
    pxNewTCB->pxTaskCode = pxTaskCode;
    pxNewTCB->pxTopOfStack = pxPortInitialiseStack( 0, pxTaskCode, pvParameters );
}

static void prvAddNewTaskToReadyList( TCB_t * pxNewTCB )
{
    prvAddTaskToReadyList( pxNewTCB );
}

void vTaskPlaceOnEventList( List_t * pxEventList, TickType_t xTicksToWait )
{
    vListInsert( pxEventList, 0 );
    prvAddCurrentTaskToDelayedList( xTicksToWait, pdTRUE );
}

BaseType_t xTaskRemoveFromEventList( const List_t * pxEventList )
{
    ( void ) pxEventList;
    prvAddTaskToReadyList( 0 );
    return pdTRUE;
}

static void prvAddCurrentTaskToDelayedList( TickType_t xTicksToWait, BaseType_t xCanBlockIndefinitely )
{
    List_t * pxDelayedList = 0;
    ( void ) xTicksToWait;
    ( void ) xCanBlockIndefinitely;
    uxListRemove( 0 );
    vListInsert( pxDelayedList, 0 );
}

void vCheckForStackOverflow( TaskHandle_t xTask, char * pcTaskName )
{
    vApplicationStackOverflowHook( xTask, pcTaskName );
}

void prvIdleTask( void )
{
    vApplicationIdleHook();
    mtCOVERAGE_TEST_MARKER();
}

void vTaskStartScheduler( void )
{
#if ( configUSE_TIMERS == 1 )
    xTimerCreateTimerTask();
#endif
    xPortStartScheduler();
}

BaseType_t xTaskIncrementTick( void )
{
    return pdTRUE;
}

void vTaskSuspendAll( void )
{
}

BaseType_t xTaskResumeAll( void )
{
    return pdTRUE;
}


BaseType_t xTaskGenericNotify( TaskHandle_t xTaskToNotify, UBaseType_t uxIndexToNotify, uint32_t ulValue, UBaseType_t eAction, uint32_t * pulPreviousNotificationValue )
{
    ( void ) xTaskToNotify;
    ( void ) uxIndexToNotify;
    ( void ) ulValue;
    ( void ) eAction;
    ( void ) pulPreviousNotificationValue;
    return pdPASS;
}

BaseType_t xTaskGenericNotifyFromISR( TaskHandle_t xTaskToNotify, UBaseType_t uxIndexToNotify, uint32_t ulValue, UBaseType_t eAction, uint32_t * pulPreviousNotificationValue, BaseType_t * pxHigherPriorityTaskWoken )
{
    ( void ) xTaskToNotify;
    ( void ) uxIndexToNotify;
    ( void ) ulValue;
    ( void ) eAction;
    ( void ) pulPreviousNotificationValue;
    ( void ) pxHigherPriorityTaskWoken;
    return pdPASS;
}

BaseType_t xTaskGenericNotifyWait( UBaseType_t uxIndexToWaitOn, uint32_t ulBitsToClearOnEntry, uint32_t ulBitsToClearOnExit, uint32_t * pulNotificationValue, TickType_t xTicksToWait )
{
    ( void ) uxIndexToWaitOn;
    ( void ) ulBitsToClearOnEntry;
    ( void ) ulBitsToClearOnExit;
    ( void ) pulNotificationValue;
    ( void ) xTicksToWait;
    return pdPASS;
}

uint32_t ulTaskGenericNotifyTake( UBaseType_t uxIndexToWaitOn, BaseType_t xClearCountOnExit, TickType_t xTicksToWait )
{
    ( void ) uxIndexToWaitOn;
    ( void ) xClearCountOnExit;
    ( void ) xTicksToWait;
    return 1;
}

#if ( configNUMBER_OF_CORES > 1 )
static void prvYieldCore( BaseType_t xCoreID )
{
    if( xCoreID == ( BaseType_t ) portGET_CORE_ID() )
    {
        portYIELD_WITHIN_API();
    }
    else
    {
        portYIELD_CORE( xCoreID );
    }
}

static void prvSelectHighestPriorityTask( BaseType_t xCoreID )
{
    if( configNUMBER_OF_CORES > 1 )
    {
        ( void ) xCoreID;
    }
    UBaseType_t uxCoreAffinityMask = 1U;
    portGET_TASK_LOCK( xCoreID );
    if( ( uxCoreAffinityMask & ( 1U << xCoreID ) ) != 0U )
    {
        prvYieldCore( xCoreID );
    }
    portRELEASE_TASK_LOCK( xCoreID );
}

BaseType_t xTaskCreateAffinitySet( TaskFunction_t pxTaskCode, const char * pcName, unsigned short usStackDepth, void * pvParameters, UBaseType_t uxPriority, UBaseType_t uxCoreAffinityMask, TaskHandle_t * pxCreatedTask )
{
    ( void ) pxTaskCode;
    ( void ) pcName;
    ( void ) usStackDepth;
    ( void ) pvParameters;
    ( void ) uxPriority;
    ( void ) uxCoreAffinityMask;
    ( void ) pxCreatedTask;
    prvSelectHighestPriorityTask( ( BaseType_t ) portGET_CORE_ID() );
    return pdPASS;
}
#endif

#if ( portUSING_MPU_WRAPPERS == 1 )
typedef struct xMEMORY_REGION
{
    void * pvBaseAddress;
    uint32_t ulLengthInBytes;
    uint32_t ulParameters;
} MemoryRegion_t;

typedef struct xTASK_PARAMETERS
{
    TaskFunction_t pvTaskCode;
    const char * pcName;
    MemoryRegion_t xRegions[ 3 ];
} TaskParameters_t;

BaseType_t xTaskCreateRestricted( const TaskParameters_t * const pxTaskDefinition, TaskHandle_t * pxCreatedTask )
{
    portRAISE_PRIVILEGE();
    vPortStoreTaskMPUSettings( 0, pxTaskDefinition->xRegions, 0, 0 );
    portRESET_PRIVILEGE();
    return xTaskCreate( pxTaskDefinition->pvTaskCode, pxTaskDefinition->pcName, 128, 0, 1, pxCreatedTask );
}

void vTaskAllocateMPURegions( TaskHandle_t xTask, const MemoryRegion_t * const xRegions )
{
    ( void ) xTask;
    vPortStoreTaskMPUSettings( 0, xRegions, 0, 0 );
}

BaseType_t MPU_xTaskCreate( TaskFunction_t pxTaskCode, const char * pcName, unsigned short usStackDepth, void * pvParameters, UBaseType_t uxPriority, TaskHandle_t * pxCreatedTask )
{
    portRAISE_PRIVILEGE();
    BaseType_t xReturn = xTaskCreate( pxTaskCode, pcName, usStackDepth, pvParameters, uxPriority, pxCreatedTask );
    portRESET_PRIVILEGE();
    return xReturn;
}

BaseType_t xPortIsAuthorizedToAccessBuffer( const void * pvBuffer, uint32_t xSize, uint32_t xAccessRequested )
{
    ( void ) pvBuffer;
    ( void ) xSize;
    ( void ) xAccessRequested;
    return pdTRUE;
}
#endif
