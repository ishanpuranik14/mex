import re
import utils
import json


def execute_function(name, parameters, context):
    # TODO this is old, put the newer one
    try:
        context_index = parameters.index('context_object')
        parameters[context_index] = context
    except ValueError:
        pass
    if hasattr("intents.py", name):
        return getattr("intents.py", name)(*parameters)
    return globals()[name](*parameters)


def get_highest_probability_intent(results, intent_utils):
    '''
    Returns the most probable intent from possible results.
    A result contains the score and the name of the possible intent
    :param results:
    :param intent_utils:
    :return:
    '''
    min_probability = intent_utils["min_probability_for_intent"]
    sorted_results = sorted(results.items(), key=lambda x: (-x[1], x[0]))
    top_probability = sorted_results[0][1]
    if top_probability < min_probability:
        return intent_utils['unknown_intent_node_name']
    return sorted_results[0][0]


def get_top_k_suggestions(data, intent_utils, search_postings, k=2):
    query = data["message"]
    query_tokens = utils.lemmatize_text(query.lower())
    query_tokens_set = set(query_tokens)
    stemmed_query_tokens = utils.stem_text(query.lower())
    for token in stemmed_query_tokens:
        if token not in query_tokens_set:
            query_tokens = query_tokens + [token]
    print "lemmatized, stemmed and stripped query tokens: " + json.dumps(query_tokens)
    # remove stop words
    # query_tokens = utils.remove_stop_words(query_tokens, input_type="list")
    results = []

    # trigger
    # the trigger shall control whether to use cosine similarity or just a sum of scores
    trigger = True

    if trigger:
        # initializations
        unique_q_tokens_with_frequencies = dict()
        postings_vocab = search_postings.get_vocabulary()
        postings_word_mapping = search_postings.get_vocabulary(return_type="dict")
        query_vector = [0] * len(postings_vocab)
        doc_set = set()

        # get tf in query
        # and get a doc set
        for q_token in query_tokens:
            freq = unique_q_tokens_with_frequencies.get(q_token, 0)
            unique_q_tokens_with_frequencies[q_token] = freq + 1
            if search_postings.get_token(q_token):
                doc_set = doc_set.union(set(map(lambda x: x["id"], search_postings.get_token(q_token).doc_list)))

        for q_token in query_tokens:
            # for this token, get the idf
            token_obj = search_postings.get_token(q_token)
            if token_obj:
                # compute tf-idf
                idf = token_obj.features["idf"]
                q_tf_idf = unique_q_tokens_with_frequencies[q_token] * idf
                # store in query vector
                query_vector[postings_word_mapping[q_token]] = q_tf_idf

        # compute cosine similarity for each doc
        for doc_id in list(doc_set):
            results.append([doc_id, utils.cosine_similarity(search_postings.doc_term_tf_idf[doc_id], query_vector)])

        # return the top k results
        sorted_results = sorted(results, key=lambda x:x[1], reverse=True)[:k]
        return map(lambda x: x[0], sorted_results)