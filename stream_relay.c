#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <time.h>
#include <signal.h>
#include <pthread.h>

#include "MQTTClient.h"

#ifdef CLOCK_MONOTONIC
#  define CLOCKID CLOCK_MONOTONIC
#else
#  define CLOCKID CLOCK_REALTIME
#endif

#define PORT        30001
#define BUFSIZE     1500
#define BUFLEN      100
#define ADDRESS     "tcp://localhost:1883"
#define CLIENTID    "StreamRelayClient"
#define TOPIC       "stream/data"
#define QOS         0
#define USERNAME    "USERNAME"
#define PASSWORD    "PASSWORD"
#define TIMEOUT     100

int finished = 0;
unsigned char buffer[BUFLEN][BUFSIZE];
int buflen [BUFLEN] = {0};
int read_idx = 0;
int write_idx = 0;
int udp_loop_running = 0;
int mqtt_client_connected = 0;

void idx_increment(int *idx) {
    ++(*idx);
    if (*idx >= BUFLEN) {
        *idx = 0;
    }
}

void signinthand(int signum) {
    printf("SIGINT received");
    finished = 1;
}

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

void *mqtt_loop() {
    // mqtt setup
    MQTTClient client;
    MQTTClient_connectOptions conn_opts = MQTTClient_connectOptions_initializer;
    int rc = 0;

    MQTTClient_create(&client, ADDRESS, CLIENTID,
        MQTTCLIENT_PERSISTENCE_NONE, NULL);

    conn_opts.keepAliveInterval = 20;
    conn_opts.cleansession = 1;
    conn_opts.username = USERNAME;
    conn_opts.password = PASSWORD;

    if ((rc = MQTTClient_connect(client, &conn_opts)) != MQTTCLIENT_SUCCESS)
    {
        printf("Failed to connect, return code %d\n", rc);
        finished = 1;
        exit(EXIT_FAILURE);
    }

    MQTTClient_message pubmsg = MQTTClient_message_initializer;
    MQTTClient_deliveryToken token;
    pubmsg.qos = QOS;
    pubmsg.retained = 0;

    printf("Starting MQTT loop\n");
    while (!finished) {
        if (buflen[read_idx] > 0) {
            pubmsg.payload = &buffer[read_idx];
            pubmsg.payloadlen = buflen[read_idx];
            MQTTClient_publishMessage(client, TOPIC, &pubmsg, &token);
            rc = MQTTClient_waitForCompletion(client, token, TIMEOUT);

            if ((rc = MQTTClient_waitForCompletion(client, token, TIMEOUT)) != MQTTCLIENT_SUCCESS)
            {
                if (rc == MQTTCLIENT_DISCONNECTED) {
                    if ((rc = MQTTClient_connect(client, &conn_opts)) != MQTTCLIENT_SUCCESS) {
                        printf("Failed to reconnect, return code %d\n", rc);
                        finished = 1;
                        exit(EXIT_FAILURE);
                    } else {
                        printf("Reconnected to the server\n");
                    }
                } else {
                    printf("Message not sent within %d milliseconds, error code: %d\n", TIMEOUT, rc);
                }
            }

            buflen[read_idx] = 0;
            idx_increment(&read_idx);
            usleep(50);
        } else {
            usleep(100);
        }
    }

    MQTTClient_disconnect(client, 10000);
    MQTTClient_destroy(&client);
    printf("MQTT client disconnected\n");
}

void *udp_loop() {
    udp_loop_running = 1;

    // udp interface setup
    int fd, recvlen;
    struct sockaddr_in myaddr;
    struct sockaddr_in remaddr;
    socklen_t addrlen = sizeof(remaddr);

    if ((fd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("cannot create socket");
        finished = 1;
        udp_loop_running = 0;
        return NULL;
    }

    printf("created socket: descriptor = %d\n", fd);

    memset((void *)&myaddr, 0, sizeof(myaddr));
    myaddr.sin_family = AF_INET;
    myaddr.sin_addr.s_addr = htonl(INADDR_ANY);
    myaddr.sin_port = htons(PORT);

    if (bind(fd, (struct sockaddr *)&myaddr, sizeof(myaddr)) < 0) {
        perror("bind failed");
        finished = 1;
        udp_loop_running = 0;
        return NULL;
    }

    // start the udp loop
    int counter = 0;
    int bytes = 0;
    uint64_t vartime = ns();
    uint64_t starttime = ns();

    printf("Starting UDP loop\n");
    while (!finished) {
        recvlen = recvfrom(fd, buffer[write_idx], BUFSIZE, 0, (struct sockaddr *)&remaddr, &addrlen);
        if (recvlen > 0) {
            buflen[write_idx] = recvlen;

            idx_increment(&write_idx);
            bytes += recvlen;
            counter++;
//            printf("looptime: %.2f ms\n", (ns() - starttime)*0.001);
//            printf("read idx: %d, write idx: %d\n", read_idx, write_idx);
            starttime = ns();
        } else {
            printf("nothing received\n");
        }

        if (counter == 100) {
            counter = 0;

            printf("datarate %f kbytes\n", bytes / (1000.f * (ns() - vartime) * 1e-9));
            vartime = ns();
            bytes = 0;
        }
    }

    udp_loop_running = 0;
    printf("UDP loop finished\n");
}


int main(int argc, char **argv) {
    // start the mqtt loop
    pthread_t thread_id;
    pthread_create(&thread_id, NULL, udp_loop, NULL);

    // start the udp loop
    int counter = 0;
    int bytes = 0;
    uint64_t vartime = ns();
    uint64_t starttime = ns();

    // add the signal handler here because this loop is not blocking
    signal(SIGINT, signinthand);

    // main mqtt loop
    mqtt_loop();

    usleep(100000);
    if (udp_loop_running) {
        printf("Stopping udp loop\n");
        pthread_kill(thread_id, SIGQUIT);
    }

    printf("Script finished\n");
    exit(0);
}
