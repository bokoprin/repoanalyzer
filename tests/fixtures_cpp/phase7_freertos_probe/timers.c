#include "FreeRTOS.h"
#include "queue.h"
#include "timers.h"

#if ( configUSE_TIMERS == 1 )

typedef struct tmrTimerControl
{
    TimerCallbackFunction_t pxCallbackFunction;
} Timer_t;

static void prvInitialiseNewTimer( TimerHandle_t xNewTimer, TimerCallbackFunction_t pxCallbackFunction );
static void prvProcessExpiredTimer( TimerHandle_t xTimer );
static void prvProcessTimerOrBlockTask( void );
static void prvProcessReceivedCommands( void );

#if ( configSUPPORT_DYNAMIC_ALLOCATION == 1 )
TimerHandle_t xTimerCreate( const char * pcTimerName, TickType_t xTimerPeriodInTicks, BaseType_t xAutoReload, void * pvTimerID, TimerCallbackFunction_t pxCallbackFunction )
{
    static Timer_t xTimer;
    Timer_t * pxNewTimer = &xTimer;
    prvInitialiseNewTimer( pxNewTimer, pxCallbackFunction );
    return pxNewTimer;
}
#endif

#if ( configSUPPORT_STATIC_ALLOCATION == 1 )
TimerHandle_t xTimerCreateStatic( const char * pcTimerName, TickType_t xTimerPeriodInTicks, BaseType_t xAutoReload, void * pvTimerID, TimerCallbackFunction_t pxCallbackFunction, void * pxTimerBuffer )
{
    static Timer_t xStaticTimer;
    ( void ) pcTimerName;
    ( void ) xTimerPeriodInTicks;
    ( void ) xAutoReload;
    ( void ) pvTimerID;
    ( void ) pxTimerBuffer;
    prvInitialiseNewTimer( &xStaticTimer, pxCallbackFunction );
    return &xStaticTimer;
}
#endif

BaseType_t xTimerCreateTimerTask( void )
{
    return pdPASS;
}

static void prvInitialiseNewTimer( TimerHandle_t xNewTimer, TimerCallbackFunction_t pxCallbackFunction )
{
    Timer_t * pxNewTimer = ( Timer_t * ) xNewTimer;
    pxNewTimer->pxCallbackFunction = pxCallbackFunction;
}

static void prvProcessTimerOrBlockTask( void )
{
    vTaskSuspendAll();
    prvProcessExpiredTimer( 0 );
    xTaskResumeAll();
}

static void prvProcessExpiredTimer( TimerHandle_t xTimer )
{
    Timer_t * pxTimer = ( Timer_t * ) xTimer;
    pxTimer->pxCallbackFunction( pxTimer );
}

static void prvProcessReceivedCommands( void )
{
    xQueueReceive( 0, 0, 0 );
}

static portTASK_FUNCTION( prvTimerTask, pvParameters )
{
    ( void ) pvParameters;
    prvProcessReceivedCommands();
}

#endif /* configUSE_TIMERS == 1 */
