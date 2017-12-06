#!/usr/bin/env python
import pika

credentials = pika.PlainCredentials('user', 'password') #enter real user and password here, TODO load from udp2rabbit.cfg
parameters = pika.ConnectionParameters('129.132.38.186', credentials=credentials)

try:
    connection = pika.BlockingConnection(parameters)
except:
    print 'connection failed'
    quit()

print 'connected'
channel = connection.channel()

print 'sending...'
channel.basic_publish(exchange='MT',
                      routing_key='',
                      body='dupa 1')

# channel.basic_publish(exchange='MO',
#                       routing_key='',
#                       body='dupa 2')
#
# channel.basic_publish(exchange='MO',
#                       routing_key='',
#                       body='dupa 3')
print 'sent'
connection.close()