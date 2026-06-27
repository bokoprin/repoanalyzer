#ifndef STREAM_BUFFER_H
#define STREAM_BUFFER_H
#include "FreeRTOS.h"
size_t xStreamBufferSend( StreamBufferHandle_t xStreamBuffer, const void * pvTxData, size_t xDataLengthBytes, TickType_t xTicksToWait );
size_t xStreamBufferReceive( StreamBufferHandle_t xStreamBuffer, void * pvRxData, size_t xBufferLengthBytes, TickType_t xTicksToWait );
size_t xMessageBufferSend( MessageBufferHandle_t xMessageBuffer, const void * pvTxData, size_t xDataLengthBytes, TickType_t xTicksToWait );
size_t xMessageBufferReceive( MessageBufferHandle_t xMessageBuffer, void * pvRxData, size_t xBufferLengthBytes, TickType_t xTicksToWait );
#endif
