# -*- coding: UTF-8 -*- 
import os
import sys
import time
import numpy as np
import tensorflow as tf
import models
from keras.utils import generic_utils
from keras.optimizers import Adam, SGD
from keras.utils import np_utils      
from keras.utils.vis_utils import plot_model  
from keras import backend as K
from keras.callbacks import TensorBoard
# Utils
sys.path.append("../utils")
import general_utils
import data_utils


# using tensorboard
def write_log(callback, names, logs, batch_no):
    for name, value in zip(names, logs):
        summary = tf.Summary()
        summary_value = summary.value.add()
        summary_value.simple_value = value
        summary_value.tag = name
        callback.writer.add_summary(summary, batch_no)
        callback.writer.flush()

def l1_loss(y_true, y_pred):
    return K.sum(K.abs(y_pred - y_true), axis=-1)


def train(**kwargs):
    """
    Train model
    Load the whole train data in memory for faster operations
    args: **kwargs (dict) keyword arguments that specify the model hyperparameters
    """

    # Roll out the parameters
    batch_size = kwargs["batch_size"]
    n_batch_per_epoch = kwargs["n_batch_per_epoch"]
    nb_epoch = kwargs["nb_epoch"]
    model_name = kwargs["model_name"]
    generator = kwargs["generator"]
    image_data_format = kwargs["image_data_format"]
    img_dim = kwargs["img_dim"]
    patch_size = kwargs["patch_size"]
    bn_mode = kwargs["bn_mode"]
    label_smoothing = kwargs["use_label_smoothing"]
    label_flipping = kwargs["label_flipping"]
    dset = kwargs["dset"]
    use_mbd = kwargs["use_mbd"]

    epoch_size = n_batch_per_epoch * batch_size

    # Setup environment (logging directory etc)
    general_utils.setup_logging(model_name)

    # Load and rescale data
    y_data, X_data, y_data_val, X_data_val = data_utils.load_data(dset, image_data_format)
    img_dim = y_data.shape[-3:]


    # Get the number of non overlapping patch and the size of input image to the discriminator
    nb_patch, img_dim_disc = data_utils.get_nb_patch(img_dim, patch_size, image_data_format) #img_dim

    try:

        # Create optimizers
        opt_dcgan = Adam(lr=1E-3, beta_1=0.9, beta_2=0.999, epsilon=1e-08)
        # opt_discriminator = SGD(lr=1E-3, momentum=0.9, nesterov=True)
        opt_discriminator = Adam(lr=1E-3, beta_1=0.9, beta_2=0.999, epsilon=1e-08)

        # Load generator model
        generator_model = models.load("generator_unet_%s" % generator,
                                      img_dim,
                                      nb_patch,
                                      bn_mode,
                                      use_mbd,
                                      batch_size)
        # Load discriminator model
        discriminator_model = models.load("DCGAN_discriminator",
                                          img_dim_disc,
                                          nb_patch,
                                          bn_mode,
                                          use_mbd,
                                          batch_size)
       
        generator_model.compile(loss='mae', optimizer=opt_discriminator)
        # plot_model(generator_model, to_file="../figures/%s.png" % "generator_unet_deconv" , show_shapes=True, show_layer_names=True)
        discriminator_model.trainable = False

        DCGAN_model = models.DCGAN(generator_model,
                                   discriminator_model,
                                   img_dim,
                                   patch_size,
                                   image_data_format)

        loss = [l1_loss, 'binary_crossentropy']
        loss_weights = [1E1, 1]
        DCGAN_model.compile(loss=loss, loss_weights=loss_weights, optimizer=opt_dcgan)

        discriminator_model.trainable = True
        discriminator_model.compile(loss='binary_crossentropy', optimizer=opt_discriminator)
        # plot_model(discriminator_model, to_file="../figures/%s.png" % "DCGAN_discriminator", show_shapes=True, show_layer_names=True)

        gen_loss = 100
        disc_loss = 100

        # before training init callback (for tensorboard log) 
        callback_DCGAN = TensorBoard('../logs/DCGAN/',write_graph=True)
        callback_DCGAN.set_model(DCGAN_model)
        train_DCGAN_names = ["train_G_tot", "train_G_L1" ,"train_G_logloss"]
        
        callback_dis = TensorBoard('../logs/Dis/',write_graph=True)
        callback_dis.set_model(discriminator_model)
        train_dis_names = ["train_D_logloss"]

        # Start training
        print("Start training")
        for e in range(nb_epoch):
            # Initialize progbar and batch counter
            progbar = generic_utils.Progbar(epoch_size)
            batch_counter = 1
            start = time.time()

            for y_data_batch, X_data_batch in data_utils.gen_batch(y_data, X_data, batch_size):

                # Create a batch to feed the discriminator model
                X_disc, y_disc = data_utils.get_disc_batch(y_data_batch,
                                                           X_data_batch,
                                                           generator_model,
                                                           batch_counter,
                                                           patch_size,
                                                           image_data_format,
                                                           label_smoothing=label_smoothing,
                                                           label_flipping=label_flipping)

                # Update the discriminator
                disc_loss = discriminator_model.train_on_batch(X_disc, y_disc)# Y_disc get the shape like [a,b],which is the out put shape
                  
                # write to tensorboard
                write_log(callback_dis, train_dis_names, [disc_loss], e)


                # Create a batch to feed the generator model
                X_gen_target, X_gen = next(data_utils.gen_batch(y_data, X_data, batch_size))
				# next() 返回迭代器的下一个项目。
				# choice() 方法返回一个列表，元组或字符串的随机项。
                y_gen = np.zeros((X_gen.shape[0], 2), dtype=np.uint8)
                y_gen[:, 1] = 1

                # Freeze the discriminator
                discriminator_model.trainable = False
                gen_loss = DCGAN_model.train_on_batch(X_gen, [X_gen_target, y_gen])

                
                # Unfreeze the discriminator
                discriminator_model.trainable = True

                batch_counter += 1
                # G total loss=loss_weights*gen_loss'
                progbar.add(batch_size, values=[("D logloss", disc_loss),
                                                ("G tot", gen_loss[0]),
                                                ("G L1", gen_loss[1]),
                                                ("G logloss", gen_loss[2])])
                
                # write to tensorboard
                write_log(callback_DCGAN, train_DCGAN_names, gen_loss, e)

                # Save images for visualization
                if batch_counter % (n_batch_per_epoch / 2) == 0:
                    # Get new images from validation
                    data_utils.plot_generated_batch(y_data_batch, X_data_batch, generator_model,
                                                    batch_size, image_data_format, "training")
                    y_data_batch, X_data_batch = next(data_utils.gen_batch(y_data_val, X_data_val, batch_size))
                    data_utils.plot_generated_batch(y_data_batch, X_data_batch, generator_model,
                                                    batch_size, image_data_format, "validation")
                    

                if batch_counter >= n_batch_per_epoch:
                    break

            print("")
            print('Epoch %s/%s, Time: %s' % (e + 1, nb_epoch, time.time() - start))

            if e % 50 == 0: # print at every 50 epoch
                gen_weights_path = os.path.join('../models/%s/gen_weights_epoch%s.h5' % (model_name, e))
                generator_model.save_weights(gen_weights_path, overwrite=True)

                disc_weights_path = os.path.join('../models/%s/disc_weights_epoch%s.h5' % (model_name, e))
                discriminator_model.save_weights(disc_weights_path, overwrite=True)

                DCGAN_weights_path = os.path.join('../models/%s/DCGAN_weights_epoch%s.h5' % (model_name, e))
                DCGAN_model.save_weights(DCGAN_weights_path, overwrite=True)
        # save model
        generator_model.save("../models/gen_model.h5")

    except KeyboardInterrupt:
        pass