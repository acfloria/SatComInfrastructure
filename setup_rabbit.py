#!/usr/bin/env python
import pika
import pika.exceptions
import sys

if len(sys.argv) != 4:
    print 'usage: %s HOSTNAME USER PASSWORD' % sys.argv[0]
    quit()

ip = sys.argv[1]
user = sys.argv[2]
pwd = sys.argv[3]

credentials = pika.PlainCredentials(user, pwd)
parameters = pika.ConnectionParameters(ip, credentials=credentials)

try:
    connection = pika.BlockingConnection(parameters)
except Exception as e:
    print 'Connection failed:'
    print type(e).__name__
    quit()

try:
    channel = connection.channel()

    channel.exchange_delete(exchange='MO')
    channel.exchange_delete(exchange='MT')

    channel.exchange_declare(exchange='MO', durable=True, exchange_type='fanout')
    channel.exchange_declare(exchange='MT', durable=True, exchange_type='fanout')

    channel.queue_delete(queue='MO')
    channel.queue_delete(queue='MO_LOG')
    channel.queue_delete(queue='MT')
    channel.queue_delete(queue='MT_LOG')

    channel.queue_declare(queue='MO', durable=True)
    channel.queue_declare(queue='MO_LOG', durable=True)
    channel.queue_declare(queue='MT', durable=True)
    channel.queue_declare(queue='MT_LOG', durable=True)

    channel.queue_bind(exchange='MO', queue='MO')
    channel.queue_bind(exchange='MO', queue='MO_LOG')
    channel.queue_bind(exchange='MT', queue='MT')
    channel.queue_bind(exchange='MT', queue='MT_LOG')

except pika.exceptions.ChannelClosed as e:
    print 'Channel closed! Error:'
    print e[1]
except Exception as e:
    print 'Error:'
    print type(e).__name__
    print e
    print e.message

connection.close()

print 'Done, kthxbye'
