#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
static void *worker(void *arg)
{
    (void)arg;
    static const char message[] = "THREAD_WORKER_ENTER\n";
    write(1, message, sizeof message - 1);
    return (void *)(uintptr_t)0x1234;
}
int main(void)
{
    pthread_t thread;
    void *value = 0;
    int rc = pthread_create(&thread, 0, worker, 0);
    printf("THREAD_CREATE=%d\n", rc);
    fflush(stdout);
    if (rc) return 1;
    rc = pthread_join(thread, &value);
    printf("THREAD_JOIN=%d VALUE=%#lx\n", rc, (unsigned long)value);
    fflush(stdout);
    return rc || value != (void *)(uintptr_t)0x1234;
}
