from __future__ import absolute_import, unicode_literals
import sys
import os
from celery import Celery
import json
import pika
from celery import bootsteps
from kombu import Consumer, Exchange, Queue


class MyConsumerStep(bootsteps.ConsumerStep):

    def get_consumers(self, channel):
        return [Consumer(channel,
                         queues=[chat_from_fb],
                         callbacks=[self.handle_message],
                         accept=['json']),
                Consumer(channel,
                         queues=[test_queue],
                         callbacks=[self.handle_test_message],
                         accept=['json']),
                Consumer(channel,
                         queues=[chat_to_fb],
                         callbacks=[self.handle_sending_message],
                         accept=['json']),
                Consumer(channel,
                         queues=[send_email],
                         callbacks=[self.handle_sending_email],
                         accept=['json'])
                ]

    def handle_message(self, body, message):
        print('Received chat message: {0!r}'.format(body))
        message.ack()
        app.send_task("tasks.chat_from_fb", [body])

    def handle_test_message(self, body, message):
        print('Received test message: {0!r}'.format(body))
        message.ack()
        # Invoke test task
        app.send_task("tasks.test", [body])

    def handle_sending_message(self, body, message):
        message.ack()
        # Invoke sending task
        app.send_task("tasks.chat_to_fb", [body])

    def handle_sending_email(self, body, message):
        message.ack()
        # Invoke task to send email
        app.send_task("tasks.send_email", [body])

# get configs
configs = dict()
with open(os.path.realpath("chatbot/configs.json")) as data_file:
    configs = json.load(data_file)


# Connect with Rabbit and declare Queues
credentials = pika.PlainCredentials(configs["celery"]["RABBIT_USR"], configs["celery"]["RABBIT_PASS"])
parameters = pika.ConnectionParameters(configs["celery"]["RABBIT_IP"],
                                       configs["celery"]["RABBIT_PORT"],
                                       configs["celery"]["RABBIT_VHOST"],
                                       credentials,
                                       socket_timeout=configs["celery"]["RABBIT_SCKT_TIMEOUT"])
connection = pika.BlockingConnection(parameters)
channel = connection.channel()

# Consume from the following
chat_from_fb = Queue(configs["celery"]["CHAT_FROM_FB"], Exchange(configs["celery"]["CHAT_FROM_FB"]), configs["celery"]["CHAT_FROM_FB"])
test_queue = Queue(configs["celery"]["TEST_TASK"], Exchange(configs["celery"]["TEST_TASK"]), configs["celery"]["TEST_TASK"])
chat_to_fb = Queue(configs["celery"]["CHAT_TO_FB"], Exchange(configs["celery"]["CHAT_TO_FB"]), configs["celery"]["CHAT_TO_FB"])
send_email = Queue(configs["celery"]["SEND_EMAIL"], Exchange(configs["celery"]["SEND_EMAIL"]), configs["celery"]["SEND_EMAIL"])

#  publish results to the following
channel.queue_declare(queue=configs["celery"]["TEST_RESULT_TASK"], durable=True)

# Initialize the app
app = Celery('chatbot',
             broker=configs["celery"]["RABBIT_MQ_URL"],
             backend='rpc://',
             include=['tasks'])

# Add custom consumer
app.steps['consumer'].add(MyConsumerStep)

# Optional configuration
app.conf.update(
    BROKER_URL=configs["celery"]["RABBIT_MQ_URL"],
    CELERY_RESULT_BACKEND='rpc',
    CELERY_RESULT_PERSISTENT=True,
    CELERY_ACCEPT_CONTENT=['json', 'msgpack', 'yaml', 'pickle', 'application/json'],
    CELERY_TASK_SERIALIZER='json',
    CELERY_RESULT_SERIALIZER='json'
)


if __name__ == '__main__':
    app.start()