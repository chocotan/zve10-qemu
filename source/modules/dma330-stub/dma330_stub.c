#include <linux/module.h>
#include <linux/kernel.h>

int dma330_mem_transfer_async(void *ctx, void *src, void *dst, unsigned int len)
{
    return 0;
}
EXPORT_SYMBOL(dma330_mem_transfer_async);

int dmac_mem_transfer_async(void *ctx, void *src, void *dst, unsigned int len)
{
    return 0;
}
EXPORT_SYMBOL(dmac_mem_transfer_async);

static int __init dma330_stub_init(void) { return 0; }
static void __exit dma330_stub_exit(void) {}
module_init(dma330_stub_init);
module_exit(dma330_stub_exit);
MODULE_LICENSE("GPL");
