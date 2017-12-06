#!/usr/bin/env python
import pika

credentials = pika.PlainCredentials('user', 'password') #enter real user and password here, TODO load from udp2rabbit.cfg
parameters = pika.ConnectionParameters('localhost',
                                       credentials=credentials)

try:
    connection = pika.BlockingConnection(parameters)
except:
    print 'connection failed'
    quit()

print 'connected'
channel = connection.channel()

def callback(ch, method, properties, body):
    print(" [x] Received %r" % body)
    ch.basic_ack(delivery_tag = method.delivery_tag)


channel.basic_consume(callback,
                      queue='MO')

channel.start_consuming()