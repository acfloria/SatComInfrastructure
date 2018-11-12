#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netdb.h>
#include <time.h>

#include <MQTTAsync.h>

#ifdef CLOCK_MONOTONIC
#  define CLOCKID CLOCK_MONOTONIC
#else
#  define CLOCKID CLOCK_REALTIME
#endif

#define PORT        19921
#define BUFSIZE     1500
#define ADDRESS     "tcp://localhost:1883"
#define CLIENTID    "GSC1"
#define TOPIC       "stream/data"
#define QOS         0
#define USERNAME    "USERNAME"
#define PASSWORD    "PASSWORD"
#define SRV_IP      "127.0.0.1"

volatile MQTTAsync_token deliveredtoken;

int fd_socket;
struct sockaddr_in myaddr;
int s_len = sizeof(myaddr);
int finished = 0;
int disc_finished = 0;
int subscribed = 0;
int id = 0;

static uint64_t ns() {
  static uint64_t is_init = 0;
    static struct timespec linux_rate;
    if (0 == is_init) {
      clock_getres(CLOCKID, &linux_rate);
      is_init = 1;
    }
    uint64_t now;
    struct timespec spec;
    clock_gettime(CLOCKID, &spec);
    now = spec.tv_sec * 1.0e9 + spec.tv_nsec;
    return now;
}

void connlost(void *context, char *cause) {
    MQTTAsync client = (MQTTAsync)context;
    MQTTAsync_connectOptions conn_opts = MQTTAsync_connectOptions_initializer;
    int rc;

    printf("\nConnection lost\n");
    if (cause)
        printf("     cause: %s\n", cause);

    printf("Reconnecting\n");
    conn_opts.keepAliveInterval = 20;
    conn_opts.cleansession = 1;
    conn_opts.username = USERNAME;
    conn_opts.password = PASSWORD;

    if ((rc = MQTTAsync_connect(client, &conn_opts)) != MQTTASYNC_SUCCESS)
    {
        printf("Failed to start connect, return code %d\n", rc);
        finished = 1;
    }
}

void onDisconnect(void* context, MQTTAsync_successData* response) {
    printf("Successful disconnection\n");
    disc_finished = 1;
}


void onSubscribe(void* context, MQTTAsync_successData* response) {
    printf("Subscribe succeeded\n");
    subscribed = 1;
}

void onSubscribeFailure(void* context, MQTTAsync_failureData* response) {
    printf("Subscribe failed, rc %d\n", response ? response->code : 0);
    finished = 1;
}


void onConnectFailure(void* context, MQTTAsync_failureData* response) {
    printf("Connect failed, rc %d\n", response ? response->code : 0);
    finished = 1;
}

void onConnect(void* context, MQTTAsync_successData* response) {
    MQTTAsync client = (MQTTAsync)context;
    MQTTAsync_responseOptions opts = MQTTAsync_responseOptions_initializer;
    int rc;

    printf("Successful connection\n");
    opts.onSuccess = onSubscribe;
    opts.onFailure = onSubscribeFailure;
    opts.context = client;

    deliveredtoken = 0;

    if ((rc = MQTTAsync_subscribe(client, TOPIC, QOS, &opts)) != MQTTASYNC_SUCCESS)
    {
        printf("Failed to start subscribe, return code %d\n", rc);
        exit(EXIT_FAILURE);
    }
}

int msgarrvd(void *context, char *topicName, int topicLen, MQTTAsync_message *message) {
    sendto(fd_socket, message->payload, message->payloadlen, 0, (const struct sockaddr*)&myaddr, s_len);
    ++id;
    return 1;
}

int main(int argc, char **argv) {
    // udp interface setup
    int recvlen;
    unsigned char buf[BUFSIZE];

    if ((fd_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)) < 0) {
        perror("cannot create socket");
        return 0;
    }

    memset((void *)&myaddr, 0, sizeof(myaddr));
    myaddr.sin_family = AF_INET;
    myaddr.sin_port = htons(PORT);

    if (inet_aton(SRV_IP, &myaddr.sin_addr)==0) {
        fprintf(stderr, "inet_aton() failed\n");
        exit(1);
    }

    // mqtt setup
    MQTTAsync client;
    MQTTAsync_connectOptions conn_opts = MQTTAsync_connectOptions_initializer;
    int rc = 0;

    MQTTAsync_create(&client, ADDRESS, CLIENTID, MQTTCLIENT_PERSISTENCE_NONE, NULL);
    MQTTAsync_setCallbacks(client, client, connlost, msgarrvd, NULL);

    conn_opts.keepAliveInterval = 20;
    conn_opts.cleansession = 1;
    conn_opts.onSuccess = onConnect;
    conn_opts.onFailure = onConnectFailure;
    conn_opts.context = client;
    conn_opts.username = USERNAME;
    conn_opts.password = PASSWORD;


    if ((rc = MQTTAsync_connect(client, &conn_opts)) != MQTTASYNC_SUCCESS)
    {
        printf("Failed to start connect, return code %d\n", rc);
        exit(EXIT_FAILURE);
    }

    while (!subscribed && !finished) {
        usleep(10000L);
    }

    // start the main loop
    while (!finished) {
        usleep(100000L);
    }

    MQTTAsync_disconnectOptions disc_opts = MQTTAsync_disconnectOptions_initializer;
    if ((rc = MQTTAsync_disconnect(client, &disc_opts)) != MQTTASYNC_SUCCESS)
    {
        printf("Failed to start disconnect, return code %d\n", rc);
        exit(EXIT_FAILURE);
    }

    while (!disc_finished) {
        usleep(10000L);
    }

    MQTTAsync_destroy(&client);

    printf("Script finished\n\n");
    exit(0);
}

