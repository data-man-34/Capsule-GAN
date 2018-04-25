import tensorflow as tf
import numpy as np
from operator import mul

batchSize=64

#def squash(vector, epsilon=1e-9):
'''
    :param vector: A tensor with shape [batch_size, 1, num_caps, vec_len, 1] or [batch_size, num_caps, vec_len, 1]
    :param epsilon: delta to prevent zero division
    :return A tensor with the same shape as vector but squashed in 'vec_len' dimension.
    '''
    #squared_norm = tf.reduce_sum(tf.square(vector), axis=-2, keep_dims=True)
    #scalar_factor = squared_norm / (1 + squared_norm) / tf.sqrt(squared_norm + epsilon)
    #return(scalar_factor * vector)

def squash(capsule, epsilon=1e-9):
    '''
    :param vector: A tensor with shape [batch_size, 1, num_caps, vec_len, 1] or [batch_size, num_caps, vec_len, 1]
    :param epsilon: delta to prevent zero division
    :return A tensor with the same shape as vector but squashed in 'vec_len' dimension.
    '''
    norm = tf.norm(capsule, axis=2)
    factor = tf.expand_dims(tf.divide(norm, tf.add(1.0, tf.add(tf.square(norm),epsilon))), 2)
    return tf.multiply(capsule, factor)


def lrelu(x, th=0.2):
    return tf.maximum(th * x, x)

def capsgen(x, initCapsuleSize = 32, batchSize = 64, isTrain = True):
    '''
    :param x: batch of randomly generated numbers (batch size x capsule length)
    :param initCapsuleSize: initial capsule size
    :return: image of (batch size x 32 x 32)
    '''
    #normalize the vector to make size of capsule 1
    x = tf.nn.l2_normalize(x, dim=1)
    x = tf.expand_dims(tf.expand_dims(x,axis=2), axis=1, name='expanded_x')    #[batch size x number of capsules x capsules length x 1]
    capsule16, W16, C16, B16= capslayer(x, layerNo=1, capsuleLength=16, numberOfCapsules=10)                        #[batch size x number of capsules x capsules length x 1]
    capsule8, W8, C8, B8 = capslayer(capsule16, layerNo=2, capsuleLength=8, numberOfCapsules=1152)                #[batch size x number of capsules x capsules length x 1]
    #print(capsule8)
    convImageSize = 6
    reshapedCaps = tf.reshape(capsule8, shape=[batchSize,convImageSize, convImageSize,-1], name="reshapedCaps")      #[batch size x x_dim x y_dim x number of filters]
    #print(reshapedCaps)
    conv1 = tf.layers.conv2d_transpose(reshapedCaps,filters=128,kernel_size=[4,4], padding="valid", name='Conv1')
    relu1 = lrelu(tf.layers.batch_normalization(conv1, training=isTrain), 0.2)

    conv2 = tf.layers.conv2d_transpose(relu1, 64, [4, 4], strides=(1, 1), padding='valid', name='Conv2')
    relu2 = lrelu(tf.layers.batch_normalization(conv2, training=isTrain), 0.2)

    conv3 = tf.layers.conv2d_transpose(relu2, 32, [5, 5], strides=(1, 1), padding='valid', name='Conv3')
    relu3 = lrelu(tf.layers.batch_normalization(conv3, training=isTrain), 0.2)

    conv4 = tf.layers.conv2d_transpose(relu3, 1, [4, 4], strides=(2, 2), padding='same', name='Conv4')
    relu4 = lrelu(tf.layers.batch_normalization(conv4, training=isTrain), 0.2)

    tanh = tf.nn.tanh(relu4,name='tanh')
    #return relu4
    return tanh, W16, C16, B16, W8, C8, B8



def generateNoisyVector(vector, outputCapsuleNumber, stddev=1.0):
    '''
    :param vector: input vector to replicate and add noise to for Routing
    :param outputCapsuleNumber: Number of Capsules in the required layer
    :return: [batch size x number of input caps x number of output caps x capsule size x 1]
    '''
    print("in gNV ", vector)
    #increase vector dimensions
    vector = tf.tile(tf.expand_dims(vector, axis=2),[1,1,outputCapsuleNumber,1,1])

    #add random noise to half the elements of the tensor
    noise = tf.random_normal(shape=tf.shape(vector),stddev=stddev)
    vector = tf.add(vector, noise)
    return vector




def modifiedDynamicRouting(inputCaps,outputCapsuleNumber, layerNo, iter=3, stddev=1.0):
    '''
    :param inputCaps:input capsule values [batch size x number of capsules x capsule length x 1]
    :param outputCapsuleNumber: number of  capsules in output
    :param iter: number of routing iterations
    :param stddev: standard deviation for controlling then noise added
    :param layerNo: Dynamic Routing for given layer number
    :return: [batch size x inputCapsuleNumber x outputCapsuleNumber x capsule length x 1]
    '''
    with tf.variable_scope("mDR" + str(layerNo)):
        print("in mDR",layerNo," ",inputCaps)
        inputShape = inputCaps.get_shape().as_list()
        #batchSize, numberOfInputCaps = inputShape[0], inputShape[1]
        numberOfInputCaps = inputShape[1]
        B = tf.Variable(name='B'+str(layerNo), trainable=False, initial_value=tf.random_normal([numberOfInputCaps, outputCapsuleNumber-1, 1, 1], dtype=tf.float32))
        expandedInput = generateNoisyVector(inputCaps, outputCapsuleNumber-1, stddev=stddev)
        #agreedValues, C = 0, 0
        for i in range(iter):
            with tf.variable_scope('iter_' + str(i)):
                # need to add a function to maintain the linear combination property
                C = tf.nn.softmax(B, axis=2)
                #print(B, C)
                agreedValues = tf.multiply(expandedInput, C)
                #print(agreedValues)
                sumExpandedCaps = tf.reduce_sum(agreedValues, axis=2)
                extraCaps = tf.expand_dims(tf.subtract(inputCaps,sumExpandedCaps), axis=2)
                if i == iter - 1:
                    agreedValues = tf.concat([agreedValues,extraCaps],axis=2)
                if i < iter - 1:
                    #reduceAgreedValues = tf.reduce_sum(tf.multiply(expandedInput, C), axis=1, keep_dims=True)
                    inputCapsExpanded = tf.expand_dims(inputCaps, dim=2)
                    #print(inputCapsExpanded)
                    A = tf.reduce_sum(tf.reduce_sum(tf.multiply(agreedValues, inputCapsExpanded), axis=3, keepdims=True),)
                    B += A
        return agreedValues, C, B





def capslayer(x, capsuleLength, numberOfCapsules, layerNo, routing = 'Modified Dynamic Routing'):
    '''
    :param x: input activation vectors [batch size x number of capsules x capsules length x 1]
    :param capsuleLength: Length of required capsules
    :param numberOfCapsules: Number of capsules in the layer
    :param: layerNo: Capsule layer number
    :param routing: routing method
    :return: capsule output vectors
    '''
    inputShape = x.get_shape().as_list()
    #batchSize = inputShape[0]
    inputCapsNum = inputShape[1]
    inputCapsLen = inputShape[-2:]
    with tf.variable_scope("Capsule"+str(layerNo)):
        if routing == 'Modified Dynamic Routing':
            routedValues, C, B = modifiedDynamicRouting(x,numberOfCapsules,layerNo=layerNo, stddev=0.05)    #[batch size x inputCapsuleNumber x outputCapsuleNumber x input capsule length x 1]
        W = tf.Variable(name='W'+str(layerNo), trainable=True, initial_value=tf.random_normal([inputCapsNum, numberOfCapsules, capsuleLength, inputCapsLen[0]]))
        Wx = tf.tile(tf.expand_dims(W,axis=0),[batchSize,1,1,1,1])      #[batch size x inputCapsNumber x numberOfCapsules, capsuleLength, input Capsule Length]
        weightedVectors = tf.matmul(Wx, routedValues)                    #[batch size x inputCapsuleNumber x outputCapsuleNumber x output capsule length x 1]
        reducedWeightedVectors = tf.reduce_sum(weightedVectors, axis=1) #[batch size x outputCapsuleNumber x output capsule length x 1]
        capsule = squash(reducedWeightedVectors)
    return capsule, W, C, B


'''
rand = tf.random_normal([64,32])
init = tf.global_variables_initializer()
sess = tf.Session()
sess.run(init)
sess.run(capsgen(rand))
'''
'''
sess = tf.InteractiveSession()
x = tf.placeholder(tf.float32, shape=(None, 32))
x_ = np.random.randn(1,32)
g = capsgen(x)
tf.global_variables_initializer().run()
#print(sess.run([g],{x:x_}))
'''

