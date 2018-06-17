from __future__ import absolute_import, unicode_literals
import sys
import os
from celery_chat import app
from graph import Graph
import actions
import utils

# Standard imports
import urllib
import requests
import pika
import redis
import json
import traceback
from pymongo import MongoClient
from bson import ObjectId
import datetime
import smtplib
import dateutil.parser


# Utility functions for encoding and decoding data
class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId) or isinstance(o, datetime.datetime):
            return str(o)
        elif isinstance(o, set):
            return list(o)

        try:
            return json.JSONEncoder.default(self, o)
        except TypeError as e:
            traceback.print_exc(file=sys.stdout)


def datetime_json_decoder(obj):
    if '__type__' in obj:
        if obj['__type__'] == '__datetime__':
            return dateutil.parser.parse(obj["value"])
    return obj


def datetime_json_loads(obj):
    return json.loads(obj, object_hook=datetime_json_decoder)


# The below are loaded in the shared memory for all workers
# So, they will be loaded only once
# get configs
configs = dict()
extraction_indices = dict()
with open(os.path.realpath("chatbot/configs.json")) as data_file:
    configs = json.load(data_file)
# TODO build a class for actions
# get configs for actions
action_configs = dict()
with open(os.path.realpath("chatbot/actionUtils.json")) as data_file:
    action_configs = json.load(data_file)
# Provide celery configs here as well
action_configs["celery"] = configs["celery"]

# Build a DB connection
db_client = MongoClient(configs["database"])
db = db_client.get_database("chat")
# Build a redis connection
# get a redis connection
r = redis.StrictRedis(host="localhost", port=6379, charset="utf-8", decode_responses=True)

# load all graphs
chat_graphs = dict()
graphs_path = "chatbot/graphs/"
for company_id in os.listdir(graphs_path):
    chat_graph = Graph(company_id)
    chat_graph.populate_graph(os.path.realpath(graphs_path + "/" + company_id), db, r, extraction_indices)
    chat_graphs[company_id] = chat_graph

# FB Bot
bot = Bot(configs["TOKEN"])

# Tasks
@app.task(ignore_result=True)
def chat_from_fb(body):
    body_json = json.loads(body)
    new_user=False
    current_node = None
    next_node = None
    move = None

    # Connections
    # Build a broker connection
    credentials = pika.PlainCredentials(configs["celery"]["RABBIT_USR"], configs["celery"]["RABBIT_PASS"])
    parameters = pika.ConnectionParameters(configs["celery"]["RABBIT_IP"],
                                           configs["celery"]["RABBIT_PORT"],
                                           configs["celery"]["RABBIT_VHOST"],
                                           credentials,
                                           socket_timeout=configs["celery"]["RABBIT_SCKT_TIMEOUT"])
    broker_connection = pika.BlockingConnection(parameters)
    channel = broker_connection.channel()

    # extract info
    message = body_json.get("message", "").replace("\\", "")
    payload = body_json.get("payload", "") or ""
    payload = payload.replace("\\", "")
    sender_id = body_json.get("sender_id", "")
    ts = body_json.get("timestamp", "")
    message_id = body_json.get("message_id", "")
    company_id = body_json.get("c_id", "")

    # get user details from cache
    # set default to "user"
    user_name = r.get(sender_id) or "user"

    # get info from db
    user = db["users"].find_one({"s_id": sender_id, "c_id": company_id})
    chat_history_doc = list(db["chathistory"].find({"s_id": sender_id, "c_id": company_id}, {"chathistory": {"$slice": -1}}))
    if chat_history_doc:
        chat_history_doc = chat_history_doc[0]
    chat_history = []
    new_chat_history = []

    # get the graph per companyID
    chat_graph = chat_graphs.get(company_id)

    # construct object to be passed everywhere
    # TODO see if this needs to be an actual object rather than a dict
    # TODO see if we can improve how its values are initialized or use an object for abstraction
    data = {
        "s_id": sender_id,
        "m_id": message_id,
        "c_id": company_id,
        "message": message.lower(),
        "payload": payload,
        "ts": ts
    }
    # This loop is for moving to a node without user interaction
    while True:
        if not user:
            # New user
            new_user = True
            user = {
                "s_id": sender_id,
                "c_id": company_id,
                "name": user_name,
                "profile_info": {},
                "context": {
                    "last_ts": ts,
                    "last_node": None
                },
            }
            next_node = chat_graph.get_node("welcome")
            # populate relevant fields in data dict
            data["name"] = user_name
            data["profile_info"] = user["profile_info"]
            data["chat_history"] = chat_history
            data["context"] = user["context"]
            data["extraction_indices"] = extraction_indices
        else:
            chat_history = chat_history_doc["chathistory"]
            data["name"] = user["name"]
            data["profile_info"] = user["profile_info"]
            data["chat_history"] = chat_history
            data["context"] = user["context"]
            data["extraction_indices"] = extraction_indices
            # clear extraction variables from context
            if move is None:
                data["context"]["extraction"] = dict()
            # Use the graph to get the next node
            # Or, get a suggestion node from previous context
            if data["context"].get("prev_node_was_suggestion", False):
                current_node = chat_graph.get_node("suggestion")
                current_node.connections = data["context"].get("suggestion_node_connections", [])
                data["context"]["suggestion_node_connections"] = []
                next_node = chat_graph.get_next_node(node=current_node, data=data) if move is None else chat_graph.get_node(
                    move)
            else:
                current_node = user.get("context", {}).get("last_node") or None
                next_node = chat_graph.get_next_node(current_node, data=data) if move is None else chat_graph.get_node(move)


        # perform action(s)
        responses, move = actions.perform_action(next_node.action, data, action_configs, channel)
        # Update context
        if data["context"].get("prev_node_was_suggestion", False):
            data["context"]["prev_node_was_suggestion"] = False
        if next_node.set_context_vars:
            for i in next_node.set_context_vars:
                if type(next_node.set_context_vars[i]) == dict and "var" in next_node.set_context_vars[i]:
                    user["context"][i] = utils.get_value_from_object(data, next_node.set_context_vars[i]["var"])
                else:
                    user["context"][i] = next_node.set_context_vars[i]
        user["context"]["last_ts"] = ts
        user["context"]["last_node"] = next_node.name
        # update chat history
        to_append = {
            "m_id": message_id,
            "ts": ts,
            "message": message,
            "payload": payload,
            "responses": responses,
            "node": next_node.name
        }
        chat_history.append(to_append)      # used for when move operation requires previous chat history
        new_chat_history.append(to_append)  # used for storing in the DB
        if move is None:
            break
    # store variables
    if new_user:
        db.users.insert(user)
    else:
        db.users.update({"s_id": sender_id, "c_id": company_id}, {"$set": {"context": user["context"]}})
    db.chathistory.update({"s_id": sender_id, "c_id": company_id}, {"$push": {"chathistory": { "$each": new_chat_history}}}, upsert=True)


@app.task(ignore_result=True)
def test(body):
    print "test message received"
    print "sending response"
    # Connections
    # Build a broker connection
    credentials = pika.PlainCredentials(configs["celery"]["RABBIT_USR"], configs["celery"]["RABBIT_PASS"])
    parameters = pika.ConnectionParameters(configs["celery"]["RABBIT_IP"],
                                           configs["celery"]["RABBIT_PORT"],
                                           configs["celery"]["RABBIT_VHOST"],
                                           credentials,
                                           socket_timeout=configs["celery"]["RABBIT_SCKT_TIMEOUT"])
    broker_connection = pika.BlockingConnection(parameters)
    channel = broker_connection.channel()
    try:
        if not broker_connection.is_closed:
            channel.basic_publish(exchange='',
                                  routing_key=configs["celery"]["TEST_RESULT_TASK"],
                                  body=json.dumps({
                                      "message": "test response"
                                  }))
            print "test response sent"
        else:
            print "test failed- broker offline"
    except Exception:
        print "test failed - error"

