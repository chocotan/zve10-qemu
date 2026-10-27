#include <assert.h>
#include <stdio.h>
#include "../source/qemu/hw/arm/zve10-gpe-init.h"
int main(void)
{
    uint32_t packet[8] = {0x0116f000,0x02056db0,0x0117f000,1,0x0044f000,0,0x0010f000,0x12345678};
    assert(zve10_gpe_init_packet(packet));
    packet[1] = 0x01000000; assert(!zve10_gpe_init_packet(packet));
    packet[1] = 0x02056db0; packet[4] = 0; assert(!zve10_gpe_init_packet(packet));
    packet[4] = 0x0044f000; packet[7] = 3; assert(!zve10_gpe_init_packet(packet));
    puts("PASS: captured initialization fence accepted; unrelated packets rejected");
}
