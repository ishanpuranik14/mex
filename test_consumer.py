import pika
import json

# Use this to consume and verify test message

def test_callback(channel, method, properties, body):
    print json.loads(body).get("message", "incorrect message received")

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

channel.basic_consume(consumer_callback=test_callback, queue="TEST_RESULT_TASK", no_ack=True)

print "starting to consume from test result queue"
channel.start_consuming()