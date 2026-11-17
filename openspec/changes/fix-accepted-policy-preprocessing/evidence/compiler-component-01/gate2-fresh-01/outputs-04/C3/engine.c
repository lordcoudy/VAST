#define STATE_FILE "engine.state"
#define DAEMON_ID "vast-component-c3"
static const char vast_c3_payload[20 << 20] = {1};
int main(void) { return vast_c3_payload[0]; }
