/* Report uid 1000 only to the OpenBot Electron binary so its "running as root" check passes.
   Every other process (Pi, bash, tools) inherits LD_PRELOAD but sees its real uid. */
#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

static int is_openbot = -1;

static int check(void) {
    if (is_openbot < 0) {
        char buf[512];
        ssize_t n = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
        buf[n > 0 ? n : 0] = 0;
        is_openbot = strcmp(buf, "/opt/openbot/app/openbot") == 0;
    }
    return is_openbot;
}

uid_t getuid(void) { return check() ? 1000 : (uid_t)syscall(SYS_getuid); }
uid_t geteuid(void) { return check() ? 1000 : (uid_t)syscall(SYS_geteuid); }

/* Outside OpenBot, drop LD_PRELOAD before main() so the agent's tools inherit a clean environment. */
__attribute__((constructor)) static void scrub(void) {
    if (!check()) unsetenv("LD_PRELOAD");
}
