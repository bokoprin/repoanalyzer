#ifndef PORTMACRO_H
#define PORTMACRO_H
#include "FreeRTOS.h"
BaseType_t xPortStartScheduler( void );
void * pxPortInitialiseStack( void * pxTopOfStack, TaskFunction_t pxCode, void * pvParameters );
void xPortSysTickHandler( void );
#define portYIELD_FROM_ISR( x ) do {} while(0)
#define portYIELD_WITHIN_API() do {} while(0)
#define portYIELD() do {} while(0)
#define portSET_INTERRUPT_MASK_FROM_ISR() 0
#define portCLEAR_INTERRUPT_MASK_FROM_ISR( x ) do {} while(0)
#define portGET_CORE_ID() 0
#define portYIELD_CORE( xCoreID ) do {} while(0)
#define portGET_TASK_LOCK( xCoreID ) do {} while(0)
#define portRELEASE_TASK_LOCK( xCoreID ) do {} while(0)
#define portGET_ISR_LOCK( xCoreID ) do {} while(0)
#define portRELEASE_ISR_LOCK( xCoreID ) do {} while(0)
#define portRAISE_PRIVILEGE() do {} while(0)
#define portRESET_PRIVILEGE() do {} while(0)
void vPortStoreTaskMPUSettings( void * xMPUSettings, const void * xRegions, void * pxBottomOfStack, uint32_t ulStackDepth );
BaseType_t xPortIsAuthorizedToAccessBuffer( const void * pvBuffer, uint32_t xSize, uint32_t xAccessRequested );
void vPortSVCHandler( void );
void xPortPendSVHandler( void );
void SecureContext_LoadContext( void );
#endif
