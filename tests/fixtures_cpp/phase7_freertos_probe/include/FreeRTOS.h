#ifndef FREERTOS_H
#define FREERTOS_H

typedef int BaseType_t;
typedef unsigned int UBaseType_t;
typedef unsigned int TickType_t;
typedef unsigned int EventBits_t;
typedef unsigned long uint32_t;
typedef unsigned long size_t;
typedef void * TaskHandle_t;
typedef void * QueueHandle_t;
typedef void * TimerHandle_t;
typedef void * StreamBufferHandle_t;
typedef void * MessageBufferHandle_t;
typedef void * EventGroupHandle_t;
typedef void * List_t;
typedef void * ListItem_t;
typedef void ( * TaskFunction_t )( void * );
typedef void ( * TimerCallbackFunction_t )( TimerHandle_t );

#define pdPASS 1
#define pdFAIL 0
#define pdTRUE 1
#define pdFALSE 0
#define portTASK_FUNCTION( vFunction, pvParameters ) void vFunction( void * pvParameters )
#define taskENTER_CRITICAL() do {} while(0)
#define taskEXIT_CRITICAL() do {} while(0)
#define taskYIELD() do {} while(0)
#define configASSERT( x ) do { ( void ) ( x ); } while(0)
#define traceTASK_CREATE( pxNewTCB ) do { ( void ) ( pxNewTCB ); } while(0)
#define traceQUEUE_SEND( xQueue ) do { ( void ) ( xQueue ); } while(0)
#define traceMALLOC( pvAddress, xSize ) do { ( void ) ( pvAddress ); ( void ) ( xSize ); } while(0)
#define mtCOVERAGE_TEST_MARKER() do {} while(0)

#endif
