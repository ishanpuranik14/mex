# mex
Mex is a context-aware chatbot-creation platform powered by Finite-State Automata. It allows creating graph-based flows for conversations in the JSON format. The platform uses the JSON files to spawn chatbots.

A conversation can be modeled as a directed graph (FSA) that contains stages as nodes and allows for complex conditional pathways between such nodes. Additional capabilities allow orphan nodes to be accessed from any part of the conversation graph at any point in time.

Mex is context-aware. It allows information to be generated and stored for a user throughout the progression of a conversation. Responses can be rendered in a variety of ways and an extensive suite of "actions" allows easy use of common and custom functions written in Python. (text extraction, Fuzzy matching, Boolean operations, etc)

Additionally, Mex supports free text queries on corpora and allows for a chat based information-retrieval. It uses the postings-powered tf-idf model and leverages cosine similarity to fetch superior results. Users need to only specify the corpus in a structured format and Mex swiftly allows users to discover content using a chat interface.

Mex can interact with any UI through the RabbitMQ message broker. It uses Redis cache and Mongo DB as the cache and database, respectively. The decoupling allows for separate development cycles for each concern. The architecture of the platform allows easy horizontal and vertical scaling without the need to modify any code. (courtesy: Celery)

Eg. 

Stage 1: User being welcomed ( the bot says "Hi <user_name>, how are you today?")
Stage 2: Processing a user's sentiment and asking them to select from a range of options being put forth as quick replies
The transition from stage 1 to stage 2 happens when the user keys in any response. this can be represented in the JSON as:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

{
  "welcome": {                                # Orphan node
    "matches": {
      "==": [
        false,
        {
          "bool": {
            "var": "context.welcomed"         # check if user hasn't been welcomed yet
          }
        }
      ]
    },
    "action": [
      {
        "text": "Hi <user_name>, how are you today?",
        "placeholders": [
          [
            "<user_name>",
            "name"
          ]
        ]
      }
    ],
    "context": {
      "welcomed": true                       # set key: value in the context
    },
    "connections": [                         # the set of nodes this node points to in the directed graph
      {
        "name": "user_feeling",
        "matches": {
          "==": [
            true,
            true
          ]
        }
      }
    ]
  },
  "user_feeling": {
    "action": [
      {
        "function": "feeling_response",      # calling a custom function
        "args": [
          "message_text",
          "context_object"
        ]
      },
      {
        "move": "ask_for_help"               # the redirection to ask for selecting among a host of services the bot can help the user with
      }
    ]
  }
 }



The JSON files need to be put under the "graphs" folder.
This project has been developed much beyond the skeleton available here. Please get in touch for customised solutions.
