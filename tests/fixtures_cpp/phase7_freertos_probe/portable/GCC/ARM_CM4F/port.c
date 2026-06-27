#include "FreeRTOS.h"
#include "task.h"
#include "portable/GCC/ARM_CM4F/portmacro.h"

BaseType_t xPortStartScheduler( void )
{
    return pdPASS;
}

void * pxPortInitialiseStack( void * pxTopOfStack, TaskFunction_t pxCode, void * pvParameters )
{
    ( void ) pxCode;
    ( void ) pvParameters;
    return pxTopOfStack;
}

void xPortSysTickHandler( void )
{
    xTaskIncrementTick();
}

void vPortSVCHandler( void )
{
    __asm volatile ( "svc 0" );
}

void xPortPendSVHandler( void )
{
    __asm volatile ( "isb" );
}

void SecureContext_LoadContext( void )
{
    __asm volatile ( "nop" );
}
