#ifndef TIMERS_H
#define TIMERS_H
#include "FreeRTOS.h"
TimerHandle_t xTimerCreate( const char * pcTimerName, TickType_t xTimerPeriodInTicks, BaseType_t xAutoReload, void * pvTimerID, TimerCallbackFunction_t pxCallbackFunction );
TimerHandle_t xTimerCreateStatic( const char * pcTimerName, TickType_t xTimerPeriodInTicks, BaseType_t xAutoReload, void * pvTimerID, TimerCallbackFunction_t pxCallbackFunction, void * pxTimerBuffer );
BaseType_t xTimerCreateTimerTask( void );
#endif
