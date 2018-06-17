import sys
import redis
import json
import ujson
import utils
import time
import pika
import re
import smtplib
import requests
import urllib


def execute_function(name, parameters, data, configs):
    '''
    Executes function in the current scope if it exists. Otherwise, tries to execute it in the global scope
    :param name:
    :param parameters:
    :param data:
    :param configs:
    :return:
    '''
    # Substitute placeholders with their equivalent data
    placeholder_map = configs["placeholders"]
    new_parameters = []
    for i, parameter in enumerate(parameters):
        if type(parameter) == dict and "var" in parameter:
            new_parameters.append(utils.get_value_from_object(data, parameter["var"]))
        elif parameter in placeholder_map:
            new_parameters.append(data[placeholder_map[parameter]])
        else:
            new_parameters.append(parameter)
    if hasattr("actions.py", name):
        return getattr("actions.py", name)(*new_parameters)
    return globals()[name](*new_parameters)


def perform_action(actions, data, configs, channel):
    '''
    given a list of actions, this function performs them all. It can use user-specific data and borrow from configs
    It publishes it's results to Rabbit MQ.
    Actions can be:
    -> Send text
    -> Call a custom function with custom arguments. Here placeholders are applicable for arguments
    :param actions:
    :param data:
    :param configs:
    :param channel:
    :return:
    '''
    # safety - hence using a copy
    actions = ujson.loads(ujson.dumps(actions))
    responses = []
    move = None
    num_actions = len(actions)
    for i, action in enumerate(actions):
        response = ""
        r_type = None
        # TODO Document all text placeholders
        if "if" in action:
            # a possible action looks like: (condition, action)
            for possible_action in action["if"]:
                if json_logic(possible_action[0], data, configs):
                    rec_response, temp_move = perform_action(possible_action[1], data, configs, channel)
                    move = temp_move or move
                    responses.extend(rec_response)
        elif "api" in action:
            # whether to get results. Later use this to spawn a separate worker
            # if result need not be fetched
            get_result = action["api"].get("get_result", True)
            result_action = action["api"].get("result_action", [])
            # call the API and get the result
            result = call_api(action["api"], data) or {}
            if get_result:
                # set the variables in data
                api_result_keys_to_set = action["api"].get("api_result", [])
                data["api_result"] = []
                for key in api_result_keys_to_set:
                    data["api_result"].append(utils.get_value_from_object(result, key))
            if result_action:
                rec_response, temp_move = perform_action(result_action, data, configs, channel)
                move = temp_move or move
                responses.extend(rec_response)
        elif "flags" in action:
            response = action["flags"]
            r_type = "flags"
        elif "urls" in action:
            response = action["urls"]
            for entry in response.get("entries", []):
                if type(entry["title"]) == dict and "var" in entry["title"]:
                    entry["title"] = utils.get_value_from_object(data, entry["title"]["var"])
                if type(entry["url"]) == dict and "var" in entry["url"]:
                    entry["url"] = utils.get_value_from_object(data, entry["url"]["var"])
            r_type = "urls"
        elif "set" in action:
            set_list = action["set"]
            if type(set_list[1]) == dict and "var" in set_list[1]:
                utils.set_value_in_object(data, set_list[0], utils.get_value_from_object(data, set_list[1]["var"]))
            else:
                utils.set_value_in_object(data, set_list[0], set_list[1])
        elif "move" in action:
            # overrides previous values of move
            move = action["move"]
            # TODO see if you want a break here and want to cascade it up
        elif "quick" in action:
            response = action["quick"]
            r_type = "quick"
        elif "suggestions" in action:
            response = action["suggestions"]
            r_type = "suggestions"
        elif "text" in action:
            text = action["text"]
            if type(text) is list:
                final_string = ""
                for element in text:
                    if type(element) == dict and "var" in element:
                        final_string = final_string + str(utils.get_value_from_object(data, element["var"]))
                    else:
                        final_string = final_string + str(substitute_placeholders(element, action, data))
                response = final_string
            else:
                response = substitute_placeholders(text, action, data)
        # Call function using arguments
        elif "send_email" in action:
            r_type = "email"
            response = execute_function(action["function"], action["args"], data, configs)
        elif "function" in action:
            response = execute_function(action["function"], action["args"], data, configs)
        if response:
            responses.append(response)
            payload = {
                "m_id": data["m_id"],
                "s_id": data["s_id"],
                "c_id": data["c_id"],
                "response": response
            }
            if "delay" in action:
                payload["delay"] = action["delay"] if action["delay"] is not True else configs["delay"]
            if r_type:
                payload["r_type"] = r_type
            if r_type == "email":
                # send to email exchange/ queue
                channel.basic_publish(exchange=configs["celery"]["SEND_EMAIL"],
                                      routing_key=configs["celery"]["SEND_EMAIL"],
                                      body=json.dumps(payload))
            else:
                # send rabbit messages
                # Adding square brackets to the payload as per format
                print payload
                channel.basic_publish(exchange="",
                                      routing_key=configs["celery"]["CHAT_TO_FB"] + "_" + payload["s_id"] + "_" + payload["c_id"],
                                      body=json.dumps([payload]))

    return responses, move


def substitute_placeholders(text, action, data):
    # TODO Placeholders are obsolete. Phase them out
    placeholders = action.get("placeholders", [])
    # Replace all placeholders in text with their value from  data
    for placeholder in placeholders:
        text = text.replace(placeholder[0], data.get(placeholder[1], ""))
    return text


def call_api(api_object, data):
    base_url = str(api_object["base_url"])
    append =  api_object.get("append", [])
    request_method = api_object.get("request_method", "post")
    to_process_append = api_object.get("process_append", False)
    for element in append:
        to_append = ""
        if type(element) == dict and "var" in element:
            to_append = utils.get_value_from_object(data, element["var"])
        else:
            to_append = element
        if type(to_append) == unicode:
            to_append = str(to_append)
            if to_process_append:
                # processes a unicode if explicitly mentioned in the form of a flag - process_append
                try:
                    to_append = urllib.quote(to_append.encode('utf8'))
                except Exception:
                    raise ValueError
        elif type(to_append) != str:
            try:
                try:
                    to_append = urllib.quote(json.dumps(to_append).encode('utf8'))
                except Exception:
                    to_append = urllib.quote(str(to_append).encode('utf8'))
            except Exception:
                raise ValueError
        else:
            if to_process_append:
                # processes a string if explicitly mentioned in the form of a flag - process_append
                try:
                    to_append = urllib.quote(to_append.encode('utf8'))
                except Exception:
                    raise ValueError
        base_url = base_url + to_append
    if request_method == "post":
        r = requests.post(url=base_url)
        # handle possible bad responses
        try:
            return json.loads(r.content or "{}")
        except Exception:
            print "Exception converting API result to JSON. API result content: " + str(r.content)
            print "URL: " + str(base_url)
            return json.loads("{}")


def json_logic(tests, data=None, action_utils=dict()):
    '''
    Evaluate JSON Logic. The matching conditions are stored in JSON
    format. This evaluator takes in relevant data and evaluates a test against the data. The boolean o/p
    is returned
    :param tests:
    :param data:
    :param action_utils:
    :return:
    '''
    # You've recursed to a primitive, stop!
    if tests is None or type(tests) != dict:
        return tests

    data = data or {}

    op = tests.keys()[0]
    values = tests[op]
    operations = {
        "==": (lambda a, b: a == b),
        "===": (lambda a, b: a is b),
        "!=": (lambda a, b: a != b),
        "!==": (lambda a, b: a is not b),
        ">": (lambda a, b: a > b),
        ">=": (lambda a, b: a >= b),
        "<": (lambda a, b, c=None: a < b if (c is None) else (a < b) and (b < c)),
        "<=": (lambda a, b, c=None: a <= b if (c is None) else (a <= b) and (b <= c)),
        "!": (lambda a: not a),
        "%": (lambda a, b: a % b),
        "and": (lambda *args: reduce(lambda total, arg: total and arg, args, True)),
        "or": (lambda *args: reduce(lambda total, arg: total or arg, args, False)),
        "?:": (lambda a, b, c: b if a else c),
        "log": (lambda a: a if sys.stdout.write(str(a)) else a),
        "in": (lambda a, b: a in b if "__contains__" in dir(b) else False),
        "var": (lambda a, not_found=None:
                reduce(lambda data, key: (data.get(key, not_found)
                                          if type(data) == dict
                                          else data[int(key)]
                if type(data) in [list, tuple]
                else not_found),
                       str(a).split("."),
                       data)),
        "cat": (lambda *args: "".join(args)),
        "+": (lambda *args: reduce(lambda total, arg: total + float(arg), args, 0.0)),
        "*": (lambda *args: reduce(lambda total, arg: total * float(arg), args, 1.0)),
        "-": (lambda a, b=None: -a if b is None else a - b),
        "/": (lambda a, b=None: a if b is None else float(a) / float(b)),
        "min": (lambda *args: min(args)),
        "max": (lambda *args: max(args)),
        "function": (lambda *args: execute_function(args[0], args[1], data.get('context', None), action_utils)),
        "regex": (lambda x, y: re.match(x, y)),
        "fuzzy": (lambda x, y: utils.fuzzy_text_matcher(x, y)),
        "fuzzyMessage": (lambda x: utils.fuzzy_text_matcher(data.get('message', ""), x) > action_utils["min_fuzzy_prob"]),
        "class": (lambda x: utils.class_check(data.get("message", ""), x, action_utils)),
        "bool": (lambda a: bool(a)),
        "extract": (lambda *x: utils.perform_extraction(x, data)),
        "count": (lambda *x: utils.length(x))
    }

    if op not in operations:
        raise RuntimeError("Unrecognized operation %s" % op)

    # Easy syntax for unary operators, like {"var": "x"} instead of strict
    # {"var": ["x"]}
    if type(values) not in [list, tuple]:
        values = [values]

    # Recursion!
    try:
        values = map(lambda val: json_logic(val, data), values)
    except RuntimeError:
        pass

    return operations[op](*values)
