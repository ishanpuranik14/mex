import sys
import os
import json
import re
import utils
import intents
from postings import Postings

class Node:
    # A node that shall encapsulate the data about an intent and peripherals
    def __init__(self, name, connections=None, action=None, matches=None, context=None, searchable=None, suggested_response=None, alias="", _id=None, no_match_before=False):
        self.name = name
        self.no_match_before = no_match_before
        self.matches = matches
        self.connections = connections or []
        self.connections_json = json.loads(json.dumps(connections)) or []
        self.action = action or dict()
        self.searchable = searchable
        self.suggested_response = suggested_response
        self.set_context_vars = context or dict()
        self.alias = alias or ""
        self.id = _id
        self.orphan = True


class Graph:
    # A class for the graph.
    # Keeps track of orphans.
    # Has a 1:1 mapping for each node
    # Allows population from data stored in a JSON

    def __init__(self, company_id="demo"):
        self.graph_id = company_id
        self.orphans = set()
        self.orphan_list = list()
        self.node_map = dict()
        self.node_id_map = dict()
        self.db_info = dict()
        self.search_postings = Postings()
        # get utils for intents.
        with open(os.path.realpath("chatbot/intentUtils.json")) as data_file:
            self.graph_utils = json.load(data_file)
            # replace escaped slashes by a single slash.
            for class_string in self.graph_utils["class"]:
                if type(self.graph_utils["class"][class_string]) is str:
                    self.graph_utils["class"][class_string] = self.graph_utils["class"][class_string].replace('\\\\', '\\')

    def get_node(self, node_name):
        return self.node_map.get(node_name)

    def get_node_by_id(self, node_id):
        return self.node_id_map.get(node_id)

    def populate_graph(self, dir_path, db_object, redis_object, extraction_indices):
        '''
        Read a stored graph from JSON files under the directory
        Read aux graph info from DB.
        Identify the orphan nodes.
        Set up the 1:1 mapping of a node name/ id with its object
        :param dir_path:
        :param db_object:
        :param redis_object:
        :param extraction_indices:
        :return:
        '''

        # initializations
        graph_json = {}
        id_counter = 0
        nodes_have_ids = False

        # read from JSON
        for file_path in os.listdir(dir_path):
            with open(dir_path + "/" + file_path) as data_file:
                graph_json.update(json.load(data_file))

        # read from DB
        self.db_info = db_object["graphdetails"].find_one({"graph_id": self.graph_id})

        # enumerate on keys
        # there are 2 cases: nodes have keys and nodes don't
        # either cases are exhaustive

        for node_key, node_json in graph_json.items():
            # get id
            node_id = node_json.get("id")
            if not nodes_have_ids and not node_id:
                node_id = id_counter
                id_counter += 1
            else:
                nodes_have_ids = True

            # get other data
            node_name = node_key
            node_no_match_before = node_json.get("no_match_before")
            node_matches = node_json.get("matches")
            node_connections = node_json.get("connections")
            node_action = node_json.get("action")
            node_context = node_json.get("context")
            node_alias = node_json.get("alias")
            node_searchable = node_json.get("searchable")
            node_suggested = node_json.get("suggested")

            current_node = Node(node_name, node_connections, node_action, node_matches, node_context, node_searchable, node_suggested, node_alias, node_id, node_no_match_before)

            # put into mappings
            self.node_map[node_name] = current_node
            self.node_id_map[node_id] = current_node

        # Enumerate over nodes and build connections
        # Also set the orphan flag for appropriate nodes

        # TODO generate auto placeholders based on mapping. Along the same lines as for actions
        for node_name, node in self.node_map.items():
            for connected_node in node.connections:
                con_node_name = connected_node["name"]
                connected_node["node"] = self.node_map.get(con_node_name)
                connected_node["node"].orphan = False

        # Add orphan nodes to the list
        # and build postings list
        for node_name, node in self.node_map.items():
            if node.orphan:
                self.orphans.add(node_name)
                self.orphan_list.append({
                    "node": node,
                    "name": node_name,
                    "matches": node.matches
                })
            self.build_postings(node)
        # compute tf-idf scores
        self.search_postings.compute_tf_idf()

        # build/ reuse postings for extraction mappings
        self.build_extraction_postings(db_object, redis_object, extraction_indices)

    def build_postings(self, node):
        if node.searchable:
            # extra weight to the question text
            # TODO make this generic. weights should be incorporated in the graph
            # TODO a default weight system should be used in case weights are not put in the graph
            searchable_text= " ".join(node.searchable) + node.searchable[0]*2
            # get lemmatized tokens
            lemmatized_tokens = utils.lemmatize_text(searchable_text.lower())
            # get stemmed tokens
            stemmed_tokens = utils.stem_text(searchable_text.lower())

            # merge the lemmatized and stemmed tokens into lmmatized_tokens
            # every stemmed token that gets put, is put as many times its versions occur in the text
            lemmatized_tokens_set = set(lemmatized_tokens)
            for token in stemmed_tokens:
                if token not in lemmatized_tokens_set:
                    lemmatized_tokens = lemmatized_tokens + [token]

            # remove stop words
            # lemmatized_tokens = utils.remove_stop_words(lemmatized_tokens, input_type="list")
            token_frequencies = dict()
            # count frequency for every lemmatized token
            for token in lemmatized_tokens:
                token_frequency = token_frequencies.get(token, 0)
                token_frequencies[token] = token_frequency + 1
            # put token and frequency info in postings
            for token in token_frequencies:
                self.search_postings.add_document_for_token(token, node.id, {"tf": token_frequencies[token]})

    def build_extraction_postings(self,db_object, redis_object, extraction_indices):
        if self.db_info and self.db_info.get("mappings"):
            map_names = self.db_info.get("mappings", []) or []
            for map_name in map_names:
                # initializations
                mapping = dict()
                postings_object = Postings()
                # skip if entry for the map exists in redis
                map_value = redis_object.get(map_name)
                # in case the entry has not been populated before
                if not map_value:
                    # get mapping from DB
                    mapping = db_object["mappings"].find_one({"name": map_name})
                    mapping.pop("_id")
                    # store mapping in Redis
                    redis_object.set(map_name, json.dumps(mapping))
                else:
                    mapping = json.loads(map_value)
                entries = mapping.get("map")
                tokenized_entries = []
                fields_to_index = mapping.get("toIndex")
                # build postings
                for i, entry in enumerate(entries):
                    # use active entries
                    if entry.get("active"):
                        # merge all texts
                        stripped_text = utils.remove_non_alpha_num_chars(" ".join(filter(lambda x: bool(x), reduce(lambda x,y: x+y, [entry.get(field, []) or [] if type(entry.get(field, []) or []) == list else [str(entry[field])] for field in fields_to_index], []))))[0]
                        # generate tokens
                        if stripped_text:
                            map(lambda x: postings_object.add_document_for_token(x, i), set(utils.lemmatize_text(stripped_text.lower())))
                        if not map_value:
                            # construct tokens for all constituents of the entry and store in redis if not already there
                            tokenized_elements = map(lambda x: sorted(utils.lemmatize_text(utils.remove_non_alpha_num_chars(x)[0])),filter(lambda x: bool(x), reduce(lambda x,y: x+y, [entry.get(field, []) or [] if type(entry.get(field, []) or []) == list else [str(entry[field])] for field in fields_to_index], [])))
                            tokenized_entries.append(tokenized_elements)
                    else:
                        if not map_value:
                            tokenized_entries.append(None)
                extraction_indices[map_name] = postings_object
                if not map_value:
                    # set tokenized mappings in redis if not already there
                    redis_object.set("tokenized" + map_name, json.dumps(tokenized_entries))

    def dump_graph(self):
        '''
        Dump the graph as a json file.
        TODO : Extend it to make it dump in a DB
        :return:
        '''
        pass

    def get_unknown_intent_node(self):
        '''
        returns the unknown_intent_node
        :return:
        '''
        return self.get_node(self.graph_utils["unknown_intent_node_name"])

    def get_next_node(self, node_name=None, node=None, data=None):
        '''
        Get the best node from a list of possible ones
        :param node_name:
        :param node:
        :param data:
        :return:
        '''
        resulting_nodes_with_confidence_values = self.get_child_confidence(node_name, node, data)
        resulting_node = self.get_node(intents.get_highest_probability_intent(resulting_nodes_with_confidence_values, self.graph_utils))
        # try to see if we can recommend other nodes
        if resulting_node.name == self.graph_utils['unknown_intent_node_name']:
            suggestions = intents.get_top_k_suggestions(data, self.graph_utils, self.search_postings, k=3)
            if suggestions:
                # get the temp node
                resulting_node = self.get_node("suggestion")
                connections_to_be_stored = json.loads(json.dumps(resulting_node.connections_json))
                # put each suggestion as a quick reply and a connection
                resulting_node.action[1]["suggestions"]["replies"] = []
                quick_replies = resulting_node.action[1]["suggestions"]["replies"]
                for index, suggestion in enumerate(suggestions):
                    suggested_node = self.get_node_by_id(suggestion)
                    suggestion_json = {
                        "name": suggested_node.suggested_response[0].get("payload", ""),
                        "matches": {
                            "or": [
                                {
                                    "fuzzyMessage": suggested_node.suggested_response[0].get("text", "")
                                },
                                {
                                    "==": [
                                        {"var": "payload"},
                                        suggested_node.name
                                    ]
                                }
                            ]
                        }
                    }
                    # If index is 0, the connection info needs to have a matching for the yes class
                    if index == 0:
                        suggestion_json["matches"]["or"].append(
                            {
                                "class": "yes"
                            }
                        )
                    # put a copy so that it can be stored in the context
                    connections_to_be_stored.append(json.loads(json.dumps(suggestion_json)))
                    suggestion_json["node"] = suggested_node
                    quick_replies.append({
                        "content_type": "text",
                        "title": suggested_node.suggested_response[0].get("text", ""),
                        "payload": suggested_node.suggested_response[0].get("payload", "")
                    })
                    resulting_node.connections.append(suggestion_json)
                # Store values in context for later retrieval.
                resulting_node.set_context_vars["suggestion_node_connections"] = connections_to_be_stored

        return resulting_node

    def get_child_confidence(self, node_name=None, node=None, data=None):
        '''
        Given the current node, and relevant data, computes the confidence values of child nodes and orphans
        :param node_name:
        :param node:
        :param data:
        :return:
        '''
        if not node and not node_name:
            return None
        # Initializations
        unknown_intent_node = self.get_unknown_intent_node()
        if not node:
            node = self.node_map[node_name]
        resulting_nodes_with_consequences = dict()

        # iterate through the current node's connections and orphan nodes and evaluate their possibility of being the
        # next node
        found = False
        for connection in node.connections + self.orphan_list:
            if not connection["node"].no_match_before or (not found and connection["node"].no_match_before):
                matching_conditions = connection["matches"]
                result = self.json_logic(matching_conditions, data)
                if result is True:
                    result = 100
                    found = True
                elif result in [False, None]:
                    result = 0
                resulting_nodes_with_consequences[connection["name"]] = result

        return resulting_nodes_with_consequences

    def json_logic(self, tests, data=None):
        '''
        Evaluate JSON Logic. The matching conditions for a node and its connections are stored in JSON
        format. This evaluator takes in relevant data and evaluates a test against the data. The boolean o/p
        is returned
        :param tests:
        :param data:
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
            "function": (lambda *args: intents.execute_function(args[0], args[1], data.get('context', None))),
            "regex": (lambda x, y: re.match(x, y)),
            "fuzzy": (lambda x, y: utils.fuzzy_text_matcher(x, y)),
            "fuzzyMessage": (lambda x: utils.fuzzy_text_matcher(data.get('message', ""), x) > self.graph_utils["min_fuzzy_prob"]),
            "class": (lambda x: utils.class_check(data.get("message", ""), x, self.graph_utils)),
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
            values = map(lambda val: self.json_logic(val, data), values)
        except RuntimeError:
            pass

        return operations[op](*values)
