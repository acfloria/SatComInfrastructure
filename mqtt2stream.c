#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netdb.h>
#include <time.h>

#include <MQTTClient.h>

#ifdef CLOCK_MONOTONIC
#  define CLOCKID CLOCK_MONOTONIC
#else
#  define CLOCKID CLOCK_REALTIME
#endif

#define PORT        19921
#define BUFSIZE     2048
#define ADDRESS     "tcp://localhost:1883"
#define CLIENTID    "GSC1"
#define TOPIC       "stream/data"
#define QOS         0
#define USERNAME    "USER"
#define PASSWORD    "PWD"

static int fd_socket;
static struct sockaddr_in myaddr;

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

int msgarrvd(void *context, char *topicName, int topicLen, MQTTClient_message *message) {
    sendto(fd_socket, message->payload, message->payloadlen, 0, (const struct sockaddr*)&myaddr, sizeof(myaddr));
    return 1;
}

void connlost(void *context, char *cause) {
    printf("\nConnection lost\n");
    printf("     cause: %s\n", cause);
}

int main(int argc, char **argv) {
    // udp interface setup
    int recvlen;
    unsigned char buf[BUFSIZE];

    if ((fd_socket = socket(AF_UNIX, SOCK_DGRAM, 0)) < 0) {
        perror("cannot create socket");
        return 0;
    }

    struct hostent *lh = gethostbyname("localhost");
    printf("hostname %d", lh->h_addrtype);

    printf("created socket: descriptor = %d\n", fd_socket);

    memset((void *)&myaddr, 0, sizeof(myaddr));
    myaddr.sin_family = AF_UNIX;
    myaddr.sin_addr.s_addr = lh->h_addrtype;
    myaddr.sin_port = htons(PORT);

    // mqtt setup
    MQTTClient client;
    MQTTClient_connectOptions conn_opts = MQTTClient_connectOptions_initializer;
    MQTTClient_message pubmsg = MQTTClient_message_initializer;
    MQTTClient_deliveryToken token;

    int rc;

    int ret = MQTTClient_create(&client, ADDRESS, CLIENTID,
        MQTTCLIENT_PERSISTENCE_NONE, NULL);
    printf("create ret: %d", ret);
    conn_opts.keepAliveInterval = 20;
    conn_opts.cleansession = 1;
    conn_opts.username = USERNAME;
    conn_opts.password = PASSWORD;

    MQTTClient_setCallbacks(client, NULL, connlost, msgarrvd, NULL);

    if ((rc = MQTTClient_connect(client, &conn_opts)) != MQTTCLIENT_SUCCESS)
    {
        printf("Failed to connect, return code %d\n", rc);
        exit(EXIT_FAILURE);
    }

    pubmsg.qos = QOS;
    pubmsg.retained = 0;

    printf("Subscribing to topic %s\nfor client %s using QoS%d\n\n"
           "Press Q<Enter> to quit\n\n", TOPIC, CLIENTID, QOS);
    MQTTClient_subscribe(client, TOPIC, QOS);

    // start the main loop
    int ch;
    do {
        ch = getchar();
    } while(ch!='Q' && ch != 'q');

    MQTTClient_unsubscribe(client, TOPIC);
    MQTTClient_disconnect(client, 10000);
    MQTTClient_destroy(&client);

    printf("Finished\n\n");
    exit(0);
}

