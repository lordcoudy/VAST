#define STATE_FILE "engine.state"
#define DAEMON_ID "vast-component-c1"
#include <stdio.h>
#include <string.h>

int main(void) {
    static const char command[] = "VAST-C1-COMMAND-V1\n";
    char buffer[64];
    size_t size = fread(buffer, 1, sizeof buffer, stdin);
    if (size != sizeof command - 1 || memcmp(buffer, command, size) != 0) {
        return 2;
    }
    FILE *state = fopen(STATE_FILE, "wx");
    if (state == NULL || fputs("ok\n", state) == EOF || fclose(state) != 0) {
        return 3;
    }
    if (fputs("VAST-C1-REPLY-V1 " DAEMON_ID "\n", stdout) == EOF || fflush(stdout) != 0) {
        return 4;
    }
    return 0;
}
