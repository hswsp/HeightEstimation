# -*- coding: UTF-8 -*- 
import math, json, os, sys
import glob
import random
import matplotlib.image as Img


import keras
from keras.callbacks import EarlyStopping, ModelCheckpoint,TensorBoard
from keras.models import Model
from keras.optimizers import Adam,SGD
from keras.layers.core import Flatten, Dense, Dropout, Activation, Lambda, Reshape
from keras.layers.convolutional import Conv2D, Deconv2D, ZeroPadding2D, UpSampling2D
from keras.layers import Input, Concatenate
from keras.layers.advanced_activations import LeakyReLU
from keras.layers.normalization import BatchNormalization
from keras.layers.pooling import MaxPooling2D
from keras import backend as K


from keras.utils import np_utils
import numpy as np
import h5py

img_row = 1024
img_cols = 1024
batch_size = 4
momentum = 0.9
base_lr = 0.01
Lambda=0.5
nb_epoch = 200

root = '/home/smiletranquilly/HeightEstimation/FCRN'
os.chdir(root)
dset = '/home/Dataset/P_V_merge/P_V_1024'
Valdir = '/home/Dataset/P_V_Val'

FCRN_dir = './model/'
log_path = './log/'

isExists=os.path.exists(FCRN_dir)    
if not isExists:
    os.makedirs(FCRN_dir) 
isExists=os.path.exists(log_path)
if not isExists:
    os.makedirs(log_path) 

def scale_invarient_error(y_true,y_pred):
    log_1=K.log(K.clip(y_pred,K.epsilon(),np.inf)+1.)
    log_2=K.log(K.clip(y_true,K.epsilon(),np.inf)+1.)
    return K.mean(K.square(log_1-log_2),axis=-1)-Lambda*K.square(K.mean(log_1-log_2,axis=-1))

def gen_batch(X1, X2, batch_size):

    while True:
        idx = np.random.choice(X1.shape[0], batch_size, replace=False) #random choice
        # X1.shape[0]为所有数据总量
        yield X1[idx], X2[idx]
        
def process_line(line):  
    tmp = Img.imread(line) 
    tmp = np.array(tmp)
    width = tmp.shape[1]
    x = tmp[:,:width//2,:]  #Data
    y = tmp[:,width//2:,:]  #label
    return x,y  
  
def generate_arrays_from_file(input_paths,batch_size):  
    while 1:  
        random.shuffle(input_paths)  
        cnt = 0  
        X =[]  
        Y =[]  
        for line in input_paths:  
            # create Numpy arrays of input data  
            # and labels, from each line in the file  
            x, y = process_line(line)  
            X.append(x)  
            Y.append(y)  
            cnt += 1  
            if cnt==batch_size:  
                cnt = 0  
                yield (np.array(X), np.array(Y))  
                X = []  
                Y = []  
     

def load_data(input_dir):
    if input_dir is None or not os.path.exists(input_dir):
        raise Exception("input_dir does not exist")
    # if DSM_dir is None or not os.path.exists(DSM_dir):
    #     raise Exception("DSM_dir does not exist")
    
    input_paths = glob.glob(os.path.join(input_dir, "*.jpg")) #返回所有匹配的文件路径列表
    # DSM_paths = glob.glob(os.path.join(DSM_dir, "*.jpg")) #返回所有匹配的文件路径列表
    if len(input_paths) == 0:
        input_paths = glob.glob(os.path.join(input_dir, "*.png")) # 没有jpg就看png
    # if len(DSM_paths) == 0:
    #     DSM_paths = glob.glob(os.path.join(DSM_dir, "*.png"))
    # input_paths = sorted(input_paths)
    # DSM_paths = sorted(DSM_paths)
    return input_paths,len(input_paths)

# net definition
def Up_Projection(x,f,num):

    x = UpSampling2D(size=(2, 2))(x)
    x1 = Conv2D(f, (5, 5), name='con5_main_'+str(num), padding="same")(x)
    x1 = Activation("relu")(x1)
    x1 = Conv2D(f, (3, 3), name='con3_main_'+str(num), padding="same")(x1)
    x2 = Conv2D(f, (5, 5), name='con5_proj_'+str(num), padding="same")(x)
    # must channel last
    x = Concatenate(axis=-1)([x1, x2])
    x = Activation("relu")(x)
    return x

def FCRN(model_name):
    # 从con层输出
    #默认参数：include_top=True, weights='imagenet',input_tensor=None, input_shape=None,
    #pooling=None, classes=1000
    inputs=Input(shape=(int(img_row/2),int(img_cols/2),3))
    base_model = keras.applications.resnet50.ResNet50(include_top=False,weights=None)
    x = Conv2D(1024, (1, 1), name='con2D_1', padding="same")(base_model.output)
    x = BatchNormalization(axis=-1)(x)
    #1024->64
    nb_conv = [9,8,7,6]
    num = 0
    for i in nb_conv:
        num = num + 1  #for name
        x = Up_Projection(x,2**i,num)
    x = Conv2D(1, (3, 3), name='con2D_last', padding="same")(x)

    FCRN =  Model(inputs=inputs,outputs=x,name = model_name)
    return FCRN

def berHu(y_true,y_pred,c):
    x = abs(y_true-y_pred)
    if x<c:
        return x
    else:
        return (x**2+c**2)/(2*c)

def step_decay(epoch):
    return base_lr * math.pow (gamma ,math.floor(epoch / stepsize))

def train():
    # Create optimizers
    opt_dcgan = Adam(lr=1E-3, beta_1=0.9, beta_2=0.999, epsilon=1e-08)
    inputs_path,train_num = load_data(dset)
    val_path,val_num = load_data(dset)
    batches = generate_arrays_from_file(inputs_path,batch_size=batch_size)
    val_batches = generate_arrays_from_file(inputs_path,batch_size=batch_size)
    # callback_dis = TensorBoard('../logs/Dis/')
    # callback_dis.set_model(discriminator_model)
    # train_dis_names = ["train_loss"]
    
    FCRNmodel = FCRN('FCRN')
    tensorboard = TensorBoard(log_dir=log_path)
    FCRNmodel.compile(loss=scale_invarient_error,optimizer=opt_dcgan,metrics=['accuracy'])
    print("Start training")
    model.fit_generator(batches,samples_per_epoch=ceil(train_num/batch_size) ,nb_epoch=nb_epoch,
    callbacks=[tensorboard],validation_data=val_batches,validation_steps=ceil(val_num/batch_size),
    max_q_size=2000,verbose=1)
    FCRNmodel.save(FCRN_dir)
    return

train()


    
    




    


