#include "FreeRTOS.h"

typedef struct A_BLOCK_LINK
{
    struct A_BLOCK_LINK * pxNextFreeBlock;
    unsigned int xBlockSize;
} BlockLink_t;

static BlockLink_t xStart;
static unsigned char ucHeap[ 128 ];

static void prvInsertBlockIntoFreeList( BlockLink_t * pxBlockToInsert )
{
    BlockLink_t * pxIterator = &xStart;
    unsigned char * puc = ( unsigned char * ) pxIterator;
    if( ( puc + pxIterator->xBlockSize ) == ( unsigned char * ) pxBlockToInsert )
    {
        pxIterator->xBlockSize += pxBlockToInsert->xBlockSize;
    }
    if( ( ( unsigned char * ) pxBlockToInsert + pxBlockToInsert->xBlockSize ) == ( unsigned char * ) pxIterator->pxNextFreeBlock )
    {
        pxBlockToInsert->xBlockSize += pxIterator->pxNextFreeBlock->xBlockSize;
    }
}

void * pvPortMalloc( unsigned int xWantedSize )
{
    void * pvReturn = ucHeap;
    if( xWantedSize == 0 )
    {
        vApplicationMallocFailedHook();
    }
    traceMALLOC( pvReturn, xWantedSize );
    return pvReturn;
}

void vPortFree( void * pv )
{
    BlockLink_t * pxLink = ( BlockLink_t * ) pv;
    if( pv != 0 )
    {
        prvInsertBlockIntoFreeList( pxLink );
    }
}
