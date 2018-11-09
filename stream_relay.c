#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <time.h>

#include <MQTTClient.h>

#ifdef CLOCK_MONOTONIC
#  define CLOCKID CLOCK_MONOTONIC
#else
#  define CLOCKID CLOCK_REALTIME
#endif

#define PORT        30000
#define BUFSIZE     2048
#define ADDRESS     "tcp://localhost:1883"
#define CLIENTID    "StreamRelayClient"
#define TOPIC       "stream/data"
#define TIMEOUT     1L
#define QOS         0
#define USERNAME    "USER"
#define PASSWORD    "PWD"

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

int main(int argc, char **argv) {
    // udp interface setup
    int fd, recvlen;
    unsigned char buf[BUFSIZE];
    struct sockaddr_in myaddr;
    struct sockaddr_in remaddr;
    socklen_t addrlen = sizeof(remaddr);

    if ((fd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("cannot create socket");
        return 0;
    }

    printf("created socket: descriptor = %d\n", fd);

    memset((void *)&myaddr, 0, sizeof(myaddr));
    myaddr.sin_family = AF_INET;
    myaddr.sin_addr.s_addr = htonl(INADDR_ANY);
    myaddr.sin_port = htons(PORT);

    if (bind(fd, (struct sockaddr *)&myaddr, sizeof(myaddr)) < 0) {
        perror("bind failed");
        return 0;
    }

    // mqtt setup
    MQTTClient client;
    MQTTClient_connectOptions conn_opts = MQTTClient_connectOptions_initializer;
    MQTTClient_message pubmsg = MQTTClient_message_initializer;
    MQTTClient_deliveryToken token;

    int rc;

    MQTTClient_create(&client, ADDRESS, CLIENTID,
        MQTTCLIENT_PERSISTENCE_NONE, NULL);
    conn_opts.keepAliveInterval = 20;
    conn_opts.cleansession = 1;
    conn_opts.username = USERNAME;
    conn_opts.password = PASSWORD;

    if ((rc = MQTTClient_connect(client, &conn_opts)) != MQTTCLIENT_SUCCESS)
    {
        printf("Failed to connect, return code %d\n", rc);
        exit(EXIT_FAILURE);
    }

    pubmsg.qos = QOS;
    pubmsg.retained = 0;

    // start the main loop
    int counter = 0;
    int bytes = 0;
    uint64_t vartime = ns();

    for (;;) {
        recvlen = recvfrom(fd, buf, BUFSIZE, 0, (struct sockaddr *)&remaddr, &addrlen);
        if (recvlen > 0) {
            pubmsg.payload = &buf;
            pubmsg.payloadlen = recvlen;
            MQTTClient_publishMessage(client, TOPIC, &pubmsg, &token);
            rc = MQTTClient_waitForCompletion(client, token, TIMEOUT);
            bytes += recvlen;
            counter++;
            buf[recvlen] = 0;
        } else {
            printf("nothing received\n");
        }
        recvlen = 0;
        if (counter == 100) {
            counter = 0;

            printf("datarate %f kbytes\n", bytes / (1000.f * (ns() - vartime) * 1e-9));
            vartime = ns();
            bytes = 0;
        }
    }

    MQTTClient_disconnect(client, 10000);
    MQTTClient_destroy(&client);

    printf("bind complete. Port number = %d\n", ntohs(myaddr.sin_port));
    exit(0);
}
