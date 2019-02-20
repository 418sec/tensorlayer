#!/usr/bin/env python
"""
This demo implements FastText[1] for sentence classification. This demo should be run in graph mode.

FastText is a simple model for text classification with performance often close
to state-of-the-art, and is useful as a solid baseline.

There are some important differences between this implementation and what
is described in the paper. Instead of Hogwild! SGD[2], we use Adam optimizer
with mini-batches. Hierarchical softmax is also not supported; if you have
a large label space, consider utilizing candidate sampling methods provided
by TensorFlow[3].

After 5 epochs, you should get test accuracy around 90.3%.

[1] Joulin, A., Grave, E., Bojanowski, P., & Mikolov, T. (2016).
    Bag of Tricks for Efficient Text Classification.
    http://arxiv.org/abs/1607.01759

[2] Recht, B., Re, C., Wright, S., & Niu, F. (2011).
    Hogwild: A Lock-Free Approach to Parallelizing Stochastic Gradient Descent.
    In Advances in Neural Information Processing Systems 24 (pp. 693–701).

[3] https://www.tensorflow.org/api_guides/python/nn#Candidate_Sampling

"""

import os
import array
import hashlib
import time
import numpy as np
import tensorflow as tf
import tensorlayer as tl
from tensorlayer.layers import *
from tensorlayer.models import *


tf.logging.set_verbosity(tf.logging.DEBUG)
tl.logging.set_verbosity(tl.logging.DEBUG)

# Hashed n-grams with 1 < n <= N_GRAM are included as features
# in addition to unigrams.
N_GRAM = 2

# Size of vocabulary; less frequent words will be treated as "unknown"
VOCAB_SIZE = 100000

# Number of buckets used for hashing n-grams
N_BUCKETS = 1000000

# Size of the embedding vectors
EMBEDDING_SIZE = 50

# Number of epochs for which the model is trained
N_EPOCH = 5

# Number of steps for printing
N_STEPS_TO_PRINT = 100

# Size of training mini-batches
BATCH_SIZE = 32

# Learning rate
LEARNING_RATE = 0.01

# Path to which to save the trained model
MODEL_FILE_PATH = 'model_static.hdf5'


class FastTextClassifier(object):
    """Simple wrapper class for creating the graph of FastText classifier."""

    def __init__(self, vocab_size, embedding_size, n_labels):
        self.vocab_size = vocab_size
        self.embedding_size = embedding_size
        self.n_labels = n_labels

        self.inputs = tf.placeholder(tf.int32, shape=[None, None], name='inputs')
        self.labels = tf.placeholder(tf.int32, shape=[None], name='labels')

        # Model structure
        net_in = Input([None, None], dtype=tf.int32)
        net = AverageEmbedding(self.vocab_size, self.embedding_size)(net_in)
        net = Dense(n_units=10)(net)
        net_out = Dense(n_units=self.n_labels)(net)
        self.model = Model(inputs=net_in, outputs=net_out, name="fast_text_classifier")

        # Training operation
        cost = tl.cost.cross_entropy(self.model(self.inputs, is_train=True).outputs, self.labels, name='cost')
        self.train_op = tf.train.AdamOptimizer(learning_rate=LEARNING_RATE).minimize(cost)

        # Predictions
        self.prediction_probs = tf.nn.softmax(self.model(self.inputs, is_train=True).outputs)
        self.predictions = tf.argmax(self.model(self.inputs, is_train=True).outputs, axis=1, output_type=tf.int32)

        # Evaluation
        are_predictions_correct = tf.equal(self.predictions, self.labels)
        self.accuracy = tf.reduce_mean(tf.cast(are_predictions_correct, tf.float32))

    def save(self, sess, filename):
        self.model.save_weights(filename, sess=sess)

    def load(self, sess, filename):
        self.model.load_weights(filename, sess=sess, in_order=False)


def augment_with_ngrams(unigrams, unigram_vocab_size, n_buckets, n=2):
    """Augment unigram features with hashed n-gram features."""

    def get_ngrams(n):
        return list(zip(*[unigrams[i:] for i in range(n)]))

    def hash_ngram(ngram):
        bytes_ = array.array('L', ngram).tobytes()
        hash_ = int(hashlib.sha256(bytes_).hexdigest(), 16)
        return unigram_vocab_size + hash_ % n_buckets

    return unigrams + [hash_ngram(ngram) for i in range(2, n + 1) for ngram in get_ngrams(i)]


def load_and_preprocess_imdb_data(n_gram=None):
    """Load IMDb data and augment with hashed n-gram features."""
    tl.logging.info("Loading and preprocessing IMDB data.")

    X_train, y_train, X_test, y_test = tl.files.load_imdb_dataset(nb_words=VOCAB_SIZE)

    if n_gram is not None:
        X_train = np.array([augment_with_ngrams(x, VOCAB_SIZE, N_BUCKETS, n=n_gram) for x in X_train])
        X_test = np.array([augment_with_ngrams(x, VOCAB_SIZE, N_BUCKETS, n=n_gram) for x in X_test])

    return X_train, y_train, X_test, y_test


def train_test_and_save_model():
    X_train, y_train, X_test, y_test = load_and_preprocess_imdb_data(N_GRAM)
    classifier = FastTextClassifier(
        vocab_size=VOCAB_SIZE + N_BUCKETS,
        embedding_size=EMBEDDING_SIZE,
        n_labels=2,
    )

    with tf.Session() as sess:
        sess.run(tf.global_variables_initializer())

        if os.path.exists(MODEL_FILE_PATH):
            # loading pre-trained model if applicable
            classifier.load(sess, MODEL_FILE_PATH)

        else:

            for epoch in range(N_EPOCH):
                start_time = time.time()
                print('Epoch %d/%d' % (epoch + 1, N_EPOCH))
                train_accuracy = list()
                for X_batch, y_batch in tl.iterate.minibatches(X_train, y_train, batch_size=BATCH_SIZE, shuffle=True):
                    accuracy, _ = sess.run(
                        [classifier.accuracy, classifier.train_op], feed_dict={
                            classifier.inputs: tl.prepro.pad_sequences(X_batch),
                            classifier.labels: y_batch,
                        }
                    )
                    train_accuracy.append(accuracy)
                    if len(train_accuracy) % N_STEPS_TO_PRINT == 0:
                        print("\t[%d/%d][%d]accuracy " % (epoch + 1, N_EPOCH, len(train_accuracy)),
                              np.mean(train_accuracy[-N_STEPS_TO_PRINT:]))

                print("\tSummary: time %.5fs, overall accuracy" % (time.time() - start_time),
                      np.mean(train_accuracy))

        test_accuracy = sess.run(
            classifier.accuracy, feed_dict={
                classifier.inputs: tl.prepro.pad_sequences(X_test),
                classifier.labels: y_test,
            }
        )
        print('Test accuracy: %.5f' % test_accuracy)

        # saving the model
        classifier.save(sess, MODEL_FILE_PATH)

if __name__ == '__main__':
    train_test_and_save_model()
