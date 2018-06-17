import os
from Levenshtein import distance
import urllib
import errno
import re
import itertools
import json
import redis
from random import randint
from nltk.stem import WordNetLemmatizer
from nltk.stem import PorterStemmer
from nltk.corpus import stopwords
from nltk import ngrams
from scipy import spatial
import html
import smtplib


def set_configs(config_file):
    '''
    Borrow configs from a file
    :param config_file: A json file having config variables and their values
    :return:
    '''
    with open(config_file) as data_file:
        configs = json.load(data_file)

    TOKEN = configs['TOKEN']
    APP_SECRET = configs['APP_SECRET']
    firebaseAddress = configs['firebaseAddress']
    port = configs['port']
    celery_configs = configs["celery"]

    return TOKEN, APP_SECRET, firebaseAddress, port, celery_configs


def is_float(value):
    '''
    Checks if input value is a float.
    :param value:
    :return:
    '''
    try:
        float(value)
        return True
    except ValueError:
        return False


def ordered(obj):
    '''
    Returns a deeply sorted list of key-valuepairs. Deeply implies internal objects are sorted as well.
    NOTE The returned obj has all keys converted into strings for now.
    :param obj:
    :return:
    '''
    if isinstance(obj, dict):
        return sorted({str(k) : ordered(v)} for k, v in obj.items())
    if isinstance(obj, list):
        return sorted(ordered(x) for x in obj)
    else:
        return str(obj)


def fuzzy_text_matcher(text_in, target):
    '''
    Performs a case insensitive fuzzy matching of inputs provided both have a length greater than 5
    returns a similarity score scaled to 100
    :param text_in:
    :param target:
    :return:
    '''
    text_in = text_in.lower()
    target = target.lower()
    text_in_len = len(text_in)
    target_len = len(target)
    if text_in == target:
        return 100

    # only apply if lengths are above the minimum threshold
    min_text_check_len = 0

    if (target_len > min_text_check_len) and (text_in_len > min_text_check_len):
        user_text_distance = distance(text_in, target)
        scaled_distance = round((user_text_distance*1.0)/(max(text_in_len, target_len)), 3)
        score = round(100.0 * (1.0 - scaled_distance), 3)
        return score

    return 0


def remove_non_alpha_num_chars(texts):
    '''
    take in a list of texts or a text and return a list of text(s) that have been stripped off of all punctuations
    and have standardized versions of acronym texts.
    :param texts:
    :return:
    '''
    if type(texts) != list:
        texts = [texts]
    modified_text = []
    for text in texts:
        if type(text) != str:
            text = str(text)
        text = text.replace("&amp;", "&")
        text = text.replace("amp;", "&")
        text = re.sub('[?!\._]', " ", text, flags=re.I)
        text = re.findall(r"[\w\.#+]+|['a-z]+|[,'\-:;\/&]", text)
        new_text  = ""
        temp_token = ""
        initial_single_token = True
        for token in text:
            if len(token) == 1 and token not in [';', ',', "'", '-', ':', "/", "&"]:
                if initial_single_token:
                    initial_single_token = False
                temp_token = temp_token + token
            else:
                if bool(temp_token):
                    temp_token = temp_token + " "
                initial_single_token = True
                new_text = new_text + temp_token + token + " "
                temp_token = ""
        new_text = new_text + temp_token
        new_text = re.sub("[\-;,:'\/]", "", new_text, flags=re.I)
        new_text = re.sub("[&]", "and", new_text, flags=re.I)
        modified_text.append(new_text.strip())
    return modified_text


def stem_text(text):
    '''
    return a list of stemmed words
    :param text:
    :return:
    '''

    # initialization
    stemmer = PorterStemmer()
    stemmed_list = []

    # get clean text
    clean_text = remove_non_alpha_num_chars(text)[0]

    # lemmatize each token
    for token in clean_text.split():
        stemmed_list.append(stemmer.stem(token))

    return stemmed_list


def lemmatize_text(text):
    '''
    Return a list of lemmatized words
    :param text:
    :return:
    '''

    # initialization
    lemmatizer = WordNetLemmatizer()
    lemmatized_list = []

    # get clean text
    clean_text = remove_non_alpha_num_chars(text)[0]

    # lemmatize each token
    for token in clean_text.split():
        lemmatized_list.append(lemmatizer.lemmatize(token))

    return lemmatized_list


def remove_stop_words(input_data, input_type="string"):
    filtered_sentence = []
    stop_words = set(stopwords.words('english'))
    if input_type == "list":
        filtered_sentence = [w for w in input_data if not w in stop_words]
    else:
        pass
    return filtered_sentence

def is_stop_word(word):
    return word.lower() in stopwords.words('english')


def word_distance(text, first_word, second_word, position_gap):
    ''' Returns True if the distance b/w occurrences if 2 given words lies between a threshold'''
    if type(text) == str:                      # convert string to list
        text = re.findall(r"[\w']+", text)

    first_word_indexes = [index for index, value in enumerate(text) if value == first_word]
    second_word_indexes = [index for index, value in enumerate(text) if value == second_word]

    distances = [(item[1] - item[0]) for item in itertools.product(first_word_indexes, second_word_indexes)]
    for distance in distances:
        if distance >= 0 and distance <= position_gap:          # words are in proximity
            return True

    return False


def is_int(s):
    '''
    Checks if a given value is an integer
    :param s:
    :return:
    '''
    try:
        int(s)
        return True
    except ValueError:
        return False


def get_random_element(no_of_elements):
    return randint(0, no_of_elements-1)


def class_check(txt, class_name, utils):
    '''
    Uses intent utils to check for certain classes in the text.
    A class can have subclasses and evaluates them in the order they appear
    returns True if found
    :param txt:
    :param class_name:
    :param utils:
    :return:
    '''
    class_regex_expns = utils["class"][class_name]
    found = False
    if isinstance(class_regex_expns, list):
        for sub_class_name in class_regex_expns:
            class_regex = re.compile(utils["class"][sub_class_name], re.IGNORECASE)
            found = re.match(class_regex, txt)
            if found:
                # TODO see if we can award a partial score here
                return 100
        return 0
    else:
        class_regex = re.compile(class_regex_expns, re.IGNORECASE)
        found = re.match(class_regex, txt)
        return 100 if found else 0


def get_value_from_object(traversable_object, value_string, not_found=None):
    '''
    given a traversable object, returns the value from within it. Can be used to traverse multiple levels inside it.
    A traversable object can be a dict, list, tuple.
    :param traversable_object:
    :param value_string:
    :param not_found:
    :return:
    '''
    try:
        return reduce(lambda data, key: (data.get(key, not_found) if type(data) == dict else data[int(key)] if type(data) in [list, tuple] else not_found),
                  str(value_string).split("."),
                  traversable_object)
    except Exception:
        return not_found


def set_value_in_object(traversable_object, reference_string, value, not_found=None):
    reference_string_split = str(reference_string).split(".")
    to_set = get_value_from_object(traversable_object, "".join(reference_string_split[:len(reference_string_split)-1]))
    if to_set is not None:
        # TODO Take care when stuff ain't there. e.g. a list aint there..or you wanna append to the list
        to_set[reference_string_split[-1]] = value
    return


def cosine_similarity(vec1, vec2):
    return 1 - spatial.distance.cosine(vec1, vec2)


def perform_extraction(ex_obj, data):
    '''
    This function can be used to extract information from a message and store it for usage.
    It returns true if any of desired information is found. Otherwise, it returns False.
    :param ex_obj:
    :param data:
    :return:
    '''
    # form a redis connection to get mapping from
    r = redis.StrictRedis(host="localhost", port=6379, charset="utf-8", decode_responses=True)
    data_found = False
    data["context"]["extraction"] = data["context"].get("extraction", {})
    # get message
    message = data.get("message")
    if message:
        message = remove_non_alpha_num_chars(message.lower())[0]
        # Loop through the array
        for element in ex_obj:
            map_name = element["map"]
            extracted_data = []
            mapping = dict()
            # check if the mapping has already been tapped into.
            if map_name not in data["context"]["extraction"]:
                # retrieve mapping
                mapping = r.get(map_name)
                tokenized_mapping = r.get("tokenized" + map_name)
                # TODO if below check fails, use function call to regenerate and populate mappings and tokenized mappings
                # TODO probably do it where the graph object will be available.
                if mapping and tokenized_mapping:
                    mapping = json.loads(mapping)
                    tokenized_mapping = json.loads(tokenized_mapping)
                    # shorten the list using index
                    shortened_mapping, shortened_tokenized_mapping = shorten_mapping(message, data["extraction_indices"][map_name], mapping.get("map", []) or [], tokenized_mapping)
                    # perform a "multi" extraction
                    extracted_data = find_occurrences(message, shortened_mapping, shortened_tokenized_mapping, "multi")
                    # set extracted values in object to prevent repeated extraction
                    data["context"]["extraction"][map_name] = extracted_data
            else:
                mapping = json.loads(r.get(map_name))
                extracted_data = data["context"]["extraction"][map_name]
            # all fields for the current map will be set. If there is no extracted value, the value shall be None
            to_set = element.get("setex", []) or [{"key": mapping["default_set_key"], "r_type": "multi"}]
            # persistent setting, if required
            to_set_persistent = element.get("set_if_exists", []) or []
            # If extraction takes place for any of the specified mappings, return True else, return False.
            if extracted_data:
                data_found = True
            # set fields using result type. If there is not data, set this fields to None
            for field_to_set in to_set:
                key_to_set = field_to_set.get("key", mapping["default_set_key"])
                r_type = field_to_set.get("r_type", "best")
                if extracted_data:
                    data["context"]["extraction"][key_to_set] = extracted_data[0] if r_type == "best" else extracted_data
                else:
                    data["context"]["extraction"][key_to_set] = None
            # set persistent data only if the required entity was extracted
            if extracted_data:
                for field_to_set in to_set_persistent:
                    # the key has to be an absolute path
                    key_to_set = field_to_set["key"]
                    r_type = field_to_set.get("r_type", "best")
                    set_value_in_object(data, key_to_set, extracted_data[0] if r_type == "best" else extracted_data)
        return data_found
    return False


def shorten_mapping(clean_string, index, mapping, tokenized_mapping):
    '''
    Shortens the incoming map using input string. This is done by using the given index.
    This improves performance as there are lesser entries to check against.
    :param clean_string:
    :param index:
    :param mapping:
    :param tokenized_mapping:
    :return:
    '''
    if clean_string and index and mapping:
        tokens = lemmatize_text(clean_string)
        doc_set = set()
        for token in tokens:
            token_obj = index.get_token(token)
            if token_obj:
                doc_set = doc_set.union(token_obj.get_doc_id_set())
        shortened_mapping = [x for i, x in enumerate(mapping) if i in doc_set]
        shortened_tokenized_mapping = [x for i, x in enumerate(tokenized_mapping) if i in doc_set]
        return shortened_mapping, shortened_tokenized_mapping
    return mapping, tokenized_mapping


def find_occurrences(clean_string, mapping, tokenized_mapping, r_type="best"):
    '''
    returns occurrences of mapping contents from inside the clean_string. response is per the specified type
    :param clean_string:
    :param mapping:
    :param tokenized_mapping:
    :param r_type:
    :return:
    '''
    if clean_string and mapping and tokenized_mapping:
        # 'found' is a dict of the indices and corresponding occurrences
        found = dict()
        tokens = lemmatize_text(clean_string)
        # the max n grams for the string will be dictated by the num of tokens
        num_tokens = len(tokens)
        for i in xrange(1, num_tokens+1):
            # generate an i gram for the token
            i_grams = ngrams(tokens, i)
            # check for each i gram
            for pos, i_gram in enumerate(i_grams):
                # sort the i gram
                sorted_i_gram = sorted(i_gram)
                # TODO optimise this. use dict and only compare i grams using i as a key in the dict.
                # TODO contd.. put it while creating the tokenized map
                found_indices = [ind for ind, x in enumerate(tokenized_mapping) if x and sorted_i_gram in x]
                # TODO Later, deal with overlapping entries being found
                # for each found index, set value in dict
                for ind in found_indices:
                    found[ind] = found.get(ind, {"name": mapping[ind]["name"], "matches":[]})
                    found[ind]["matches"].append((pos, i))
        # use criteria to deliver best one if required. for now, deliver the first found.
        # TODO later make it configurable so that criteria can be specified in the graph.
        sorted_occurrences = map(lambda x: x["name"], sorted(found.itervalues(), key=lambda y: min(map(lambda z: z[0], y["matches"])), reverse=True))
        if not sorted_occurrences:
            return []
        if r_type == "best":
            return [sorted_occurrences[0]]
        return sorted_occurrences
    return []


def length(obj):
    '''
    returns the length of applicable objects. otherwise returns -1
    :param obj:
    :return:
    '''
    try:
        if "__len__" in obj:
            return len(obj)
    except:
        pass
    return -1
