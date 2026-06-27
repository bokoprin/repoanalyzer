#include "FreeRTOS.h"
#include "stream_buffer.h"
#include "task.h"

static size_t prvWriteBytesToBuffer( StreamBufferHandle_t xStreamBuffer, const void * pvTxData, size_t xDataLengthBytes );
static size_t prvReadBytesFromBuffer( StreamBufferHandle_t xStreamBuffer, void * pvRxData, size_t xBufferLengthBytes );
static size_t prvWriteMessageToBuffer( MessageBufferHandle_t xMessageBuffer, const void * pvTxData, size_t xDataLengthBytes );
static size_t prvReadMessageFromBuffer( MessageBufferHandle_t xMessageBuffer, void * pvRxData, size_t xBufferLengthBytes );

size_t xStreamBufferSend( StreamBufferHandle_t xStreamBuffer, const void * pvTxData, size_t xDataLengthBytes, TickType_t xTicksToWait )
{
    ( void ) xTicksToWait;
    return prvWriteBytesToBuffer( xStreamBuffer, pvTxData, xDataLengthBytes );
}

size_t xStreamBufferReceive( StreamBufferHandle_t xStreamBuffer, void * pvRxData, size_t xBufferLengthBytes, TickType_t xTicksToWait )
{
    ( void ) xTicksToWait;
    return prvReadBytesFromBuffer( xStreamBuffer, pvRxData, xBufferLengthBytes );
}

size_t xMessageBufferSend( MessageBufferHandle_t xMessageBuffer, const void * pvTxData, size_t xDataLengthBytes, TickType_t xTicksToWait )
{
    ( void ) xTicksToWait;
    return prvWriteMessageToBuffer( xMessageBuffer, pvTxData, xDataLengthBytes );
}

size_t xMessageBufferReceive( MessageBufferHandle_t xMessageBuffer, void * pvRxData, size_t xBufferLengthBytes, TickType_t xTicksToWait )
{
    ( void ) xTicksToWait;
    return prvReadMessageFromBuffer( xMessageBuffer, pvRxData, xBufferLengthBytes );
}

static size_t prvWriteBytesToBuffer( StreamBufferHandle_t xStreamBuffer, const void * pvTxData, size_t xDataLengthBytes )
{
    ( void ) xStreamBuffer;
    ( void ) pvTxData;
    return xDataLengthBytes;
}

static size_t prvReadBytesFromBuffer( StreamBufferHandle_t xStreamBuffer, void * pvRxData, size_t xBufferLengthBytes )
{
    ( void ) xStreamBuffer;
    ( void ) pvRxData;
    return xBufferLengthBytes;
}

static size_t prvWriteMessageToBuffer( MessageBufferHandle_t xMessageBuffer, const void * pvTxData, size_t xDataLengthBytes )
{
    ( void ) xMessageBuffer;
    ( void ) pvTxData;
    return xDataLengthBytes;
}

static size_t prvReadMessageFromBuffer( MessageBufferHandle_t xMessageBuffer, void * pvRxData, size_t xBufferLengthBytes )
{
    ( void ) xMessageBuffer;
    ( void ) pvRxData;
    return xBufferLengthBytes;
}
