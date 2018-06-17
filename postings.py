import math
import utils

class PostingsNode:
    def __init__(self, token):
        self.token = token
        self.features = {}
        self.doc_list = []
        self.doc_id_set = set()

    def get_doc_id_set(self):
        return set(map(lambda x: x["id"], self.doc_list))


class Postings:
    def __init__(self):
        self.collection = {}
        self.total_docs = -1
        self.vocabulary = []
        self.mapped_vocabulary = {}
        self.docs = []
        self.doc_term_tf_idf = {}

    def get_token(self, token, default_value=None):
        return self.collection.get(token, default_value)

    def add_token(self, token, return_postings=False):
        '''
        add a token object to the postings
        :param token:
        :param return_postings:
        :return:
        '''
        self.collection[token] = PostingsNode(token=token)
        if return_postings:
            return self.collection[token]

    def get_doc_list(self):
        '''
        return a sorted list of documents (ids)
        USE THIS ONLY AFTER ALL THE TOKENS HAVE BEEN POPULATED IN THE COLLECTION
        :return:
        '''
        doc_set = set()
        if len(self.docs) == 0:
            for token in self.collection:
                doc_set = doc_set.union(set(map(lambda x: x["id"], self.collection[token].doc_list)))
            self.docs = sorted(list(doc_set))
        return self.docs

    def get_num_docs(self):
        '''
        Returns the number of docs, at the time of calling, after setting a non-negative integer as the value of total_docs
        doesnt change the -1 value of total_docs if the number of docs is 0.
        :return:
        '''
        if self.total_docs != -1:
            return self.total_docs

        len_doc_list = len(self.get_doc_list())
        if len_doc_list:
            self.total_docs = len_doc_list
        return self.total_docs

    def get_vocabulary(self, return_type="list"):
        '''
        returns a sorted list of tokens or a dict that maps a token to its index in the sorted_list
        :return:
        '''
        if len(self.vocabulary) == 0:
            self.vocabulary = sorted(list(self.collection))
        if return_type == "list":
            return self.vocabulary
        else:
            if len(self.mapped_vocabulary) == 0:
                for index, val in enumerate(self.vocabulary):
                    self.mapped_vocabulary[val] = index
            return self.mapped_vocabulary

    def add_document_for_token(self, token, doc_id, doc_features=dict()):
        '''
        adds a document and its features to a token object. It creates a token object if not there
        :param token:
        :param doc_id:
        :param doc_features:
        :return:
        '''
        node = self.get_token(token)
        # add token if not there
        if not node:
            self.add_token(token)
            node = self.get_token(token)
        node.doc_list.append({
            "id": doc_id,
            "features": doc_features
        })

    def compute_tf_idf(self):
        '''
        Computes idf for all the tokens in the postings and stores as their features.
        also computes tf-idf for all token-doc pairs.
        Also populates doc-term adjascency using tf-idf
        NEEDS the total number of docs. Call this function only after the postings has been populated in a
        basic way
        :return:
        '''
        # handling erroneous case
        if self.get_num_docs() == -1:
            print "no documents"
            return


        token_list = self.get_vocabulary()
        token_mapping = self.get_vocabulary(return_type="dict")
        num_tokens = len(token_list)
        for token in token_list:
            token_obj = self.get_token(token)
            doc_count = len(token_obj.doc_list)
            idf = math.log(self.get_num_docs()/doc_count)
            # reduce idf if the token is a stop word
            if utils.is_stop_word(token):
                idf /= 2                        # modify this based on experiments
            token_obj.features["doc_count"] = doc_count
            token_obj.features["idf"] = idf
            for doc in token_obj.doc_list:
                tf = doc["features"]["tf"]
                # similarly, other metrics can also be put
                tf_idf = tf*idf
                doc["features"]["tf-idf"] = tf_idf
                # populate entry in doc-term tf-idf adjascency list
                if doc["id"] not in self.doc_term_tf_idf:
                    self.doc_term_tf_idf[doc["id"]] = [0] * num_tokens
                self.doc_term_tf_idf[doc["id"]][token_mapping[token]] = tf_idf
