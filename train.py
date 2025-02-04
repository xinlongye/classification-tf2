from functools import partial

import numpy as np
import tensorflow as tf
from tensorflow.keras.callbacks import EarlyStopping, TensorBoard
from tensorflow.keras.optimizers import Adam

from nets import freeze_layers, get_model_from_name
from utils.callbacks import (ExponentDecayScheduler, LossHistory,
                             ModelCheckpoint)
from utils.dataloader import ClsDatasets
from utils.utils import get_classes
from utils.utils_fit import fit_one_epoch

gpus = tf.config.experimental.list_physical_devices(device_type='GPU')
for gpu in gpus:
    tf.config.experimental.set_memory_growth(gpu, True)

# ----------------------------------------#
#   主函数
# ----------------------------------------#
if __name__ == "__main__":
    # ----------------------------------------------------#
    #   是否使用eager模式训练
    # ----------------------------------------------------#
    eager = False
    # ------------------------------------------------------#
    #   训练自己的数据集的时候一定要注意修改classes_path
    #   修改成自己数据集所区分的种类对应的txt文件
    # ------------------------------------------------------#
    classes_path = 'model_data/cls_classes.txt'
    # ------------------------------------------------------#
    #   输入的图片大小
    # ------------------------------------------------------#
    input_shape = [224, 224]
    # ------------------------------------------------------#
    #   所用模型种类：
    #   mobilenet、resnet50、vgg16是常用的分类网络
    # ------------------------------------------------------#
    backbone = "mobilenet"
    # ------------------------------------------------------#
    #   当使用mobilenet的alpha值
    #   仅在backbone='mobilenet'的时候有效
    # ------------------------------------------------------#
    alpha = 0.25
    # ----------------------------------------------------------------------------------------------------------------------------#
    #   权值文件的下载请看README，可以通过网盘下载。模型的 预训练权重 对不同数据集是通用的，因为特征是通用的。
    #   模型的 预训练权重 比较重要的部分是 主干特征提取网络的权值部分，用于进行特征提取。
    #   预训练权重对于99%的情况都必须要用，不用的话主干部分的权值太过随机，特征提取效果不明显，网络训练的结果也不会好
    #
    #   如果训练过程中存在中断训练的操作，可以将model_path设置成logs文件夹下的权值文件，将已经训练了一部分的权值再次载入。
    #   同时修改下方的 冻结阶段 或者 解冻阶段 的参数，来保证模型epoch的连续性。
    #   
    #   当model_path = ''的时候不加载整个模型的权值。
    #
    #   此处使用的是整个模型的权重，因此是在train.py进行加载的。
    #   如果想要让模型从主干的预训练权值开始训练，则设置model_path为主干网络的权值，此时仅加载主干。
    #   如果想要让模型从0开始训练，则设置model_path = ''，Freeze_Train = Fasle，此时从0开始训练，且没有冻结主干的过程。
    # ----------------------------------------------------------------------------------------------------------------------------#
    model_path = "model_data/mobilenet_2_5_224_tf_no_top.h5"
    # ------------------------------------------------------#
    #   是否进行冻结训练，默认先冻结主干训练后解冻训练。
    # ------------------------------------------------------#
    Freeze_Train = True
    # ------------------------------------------------------#
    #   获得图片路径和标签
    # ------------------------------------------------------#
    annotation_path = "cls_train.txt"
    # ------------------------------------------------------#
    #   进行训练集和验证集的划分，默认使用10%的数据用于验证
    # ------------------------------------------------------#
    val_split = 0.1
    # ------------------------------------------------------#
    #   用于设置是否使用多线程读取数据，1代表关闭多线程
    #   开启后会加快数据读取速度，但是会占用更多内存
    #   在IO为瓶颈的时候再开启多线程，即GPU运算速度远大于读取图片的速度。
    # ------------------------------------------------------#
    num_workers = 1

    # ------------------------------------------------------#
    #   获取classes
    # ------------------------------------------------------#
    class_names, num_classes = get_classes(classes_path)

    assert backbone in ["mobilenet", "resnet50", "vgg16"]
    # ------------------------------------------------------#
    #   创建分类模型
    # ------------------------------------------------------#
    if backbone == "mobilenet":
        model = get_model_from_name[backbone](input_shape=[input_shape[0], input_shape[1], 3], classes=num_classes,
                                              alpha=alpha)
    else:
        model = get_model_from_name[backbone](input_shape=[input_shape[0], input_shape[1], 3], classes=num_classes)

    if model_path != "":
        # ------------------------------------------------------#
        #   载入预训练权重
        # ------------------------------------------------------#
        print('Load weights {}.'.format(model_path))
        model.load_weights(model_path, by_name=True, skip_mismatch=True)

    # -------------------------------------------------------------------------------#
    #   训练参数的设置
    #   logging表示tensorboard的保存地址
    #   checkpoint用于设置权值保存的细节，period用于修改多少epoch保存一次
    #   reduce_lr用于设置学习率下降的方式
    #   early_stopping用于设定早停，val_loss多次不下降自动结束训练，表示模型基本收敛
    # -------------------------------------------------------------------------------#
    logging = TensorBoard(log_dir='logs/')
    checkpoint = ModelCheckpoint('logs/ep{epoch:03d}-loss{loss:.3f}-val_loss{val_loss:.3f}.h5',
                                 monitor='val_loss', save_weights_only=True, save_best_only=False, period=1)
    reduce_lr = ExponentDecayScheduler(decay_rate=0.94, verbose=1)
    early_stopping = EarlyStopping(monitor='val_loss', min_delta=0, patience=10, verbose=1)
    loss_history = LossHistory('logs/')

    # ----------------------------------------------------#
    #   验证集的划分在train.py代码里面进行
    # ----------------------------------------------------#
    with open(annotation_path, "r") as f:
        lines = f.readlines()
    np.random.seed(10101)
    np.random.shuffle(lines)
    np.random.seed(None)
    num_val = int(len(lines) * val_split)
    num_train = len(lines) - num_val

    if Freeze_Train:
        for i in range(freeze_layers[backbone]):
            model.layers[i].trainable = False

    # ------------------------------------------------------#
    #   主干特征提取网络特征通用，冻结训练可以加快训练速度
    #   也可以在训练初期防止权值被破坏。
    #   Init_Epoch为起始世代
    #   Freeze_Epoch为冻结训练的世代
    #   Epoch总训练世代
    #   提示OOM或者显存不足请调小batch_size
    # ------------------------------------------------------#
    if True:
        # --------------------------------------------#
        #   batch_size不要太小，不然训练效果很差
        # --------------------------------------------#
        batch_size = 32
        Lr = 1e-3
        Init_Epoch = 0
        Freeze_Epoch = 50

        epoch_step = num_train // batch_size
        epoch_step_val = num_val // batch_size

        if epoch_step == 0 or epoch_step_val == 0:
            raise ValueError('数据集过小，无法进行训练，请扩充数据集。')

        print('Train on {} samples, val on {} samples, with batch size {}.'.format(num_train, num_val, batch_size))

        train_dataloader = ClsDatasets(lines[:num_train], input_shape, batch_size, num_classes, train=True)
        val_dataloader = ClsDatasets(lines[num_train:], input_shape, batch_size, num_classes, train=False)

        if eager:
            gen = tf.data.Dataset.from_generator(partial(train_dataloader.generate), (tf.float32, tf.float32))
            gen_val = tf.data.Dataset.from_generator(partial(val_dataloader.generate), (tf.float32, tf.float32))

            gen = gen.shuffle(buffer_size=batch_size).prefetch(buffer_size=batch_size)
            gen_val = gen_val.shuffle(buffer_size=batch_size).prefetch(buffer_size=batch_size)

            lr_schedule = tf.keras.optimizers.schedules.ExponentialDecay(
                initial_learning_rate=Lr, decay_steps=epoch_step, decay_rate=0.95, staircase=True
            )
            optimizer = tf.keras.optimizers.Adam(learning_rate=lr_schedule)

            for epoch in range(Init_Epoch, Freeze_Epoch):
                fit_one_epoch(model, loss_history, optimizer, epoch, epoch_step, epoch_step_val, gen, gen_val,
                              Freeze_Epoch)

        else:
            model.compile(loss='categorical_crossentropy',
                          optimizer=Adam(lr=Lr),
                          metrics=['categorical_accuracy'])

            model.fit_generator(
                generator=train_dataloader,
                steps_per_epoch=epoch_step,
                validation_data=val_dataloader,
                validation_steps=epoch_step_val,
                epochs=Freeze_Epoch,
                initial_epoch=Init_Epoch,
                use_multiprocessing=True if num_workers > 1 else False,
                workers=num_workers,
                callbacks=[logging, checkpoint, reduce_lr, early_stopping, loss_history]
            )

    for i in range(freeze_layers[backbone]):
        model.layers[i].trainable = True

    if True:
        # --------------------------------------------#
        #   batch_size不要太小，不然训练效果很差
        # --------------------------------------------#
        batch_size = 32
        Lr = 1e-4
        Freeze_Epoch = 50
        Epoch = 100

        epoch_step = num_train // batch_size
        epoch_step_val = num_val // batch_size

        if epoch_step == 0 or epoch_step_val == 0:
            raise ValueError("数据集过小，无法进行训练，请扩充数据集。")

        print('Train on {} samples, val on {} samples, with batch size {}.'.format(num_train, num_val, batch_size))

        train_dataloader = ClsDatasets(lines[:num_train], input_shape, batch_size, num_classes, train=True)
        val_dataloader = ClsDatasets(lines[num_train:], input_shape, batch_size, num_classes, train=False)

        if eager:
            gen = tf.data.Dataset.from_generator(partial(train_dataloader.generate), (tf.float32, tf.float32))
            gen_val = tf.data.Dataset.from_generator(partial(val_dataloader.generate), (tf.float32, tf.float32))

            gen = gen.shuffle(buffer_size=batch_size).prefetch(buffer_size=batch_size)
            gen_val = gen_val.shuffle(buffer_size=batch_size).prefetch(buffer_size=batch_size)

            lr_schedule = tf.keras.optimizers.schedules.ExponentialDecay(
                initial_learning_rate=Lr, decay_steps=epoch_step, decay_rate=0.95, staircase=True
            )
            optimizer = tf.keras.optimizers.Adam(learning_rate=lr_schedule)

            for epoch in range(Freeze_Epoch, Epoch):
                fit_one_epoch(model, loss_history, optimizer, epoch, epoch_step, epoch_step_val, gen, gen_val, Epoch)

        else:
            model.compile(loss='categorical_crossentropy',
                          optimizer=Adam(lr=Lr),
                          metrics=['categorical_accuracy'])

            model.fit_generator(
                generator=train_dataloader,
                steps_per_epoch=epoch_step,
                validation_data=val_dataloader,
                validation_steps=epoch_step_val,
                epochs=Epoch,
                initial_epoch=Freeze_Epoch,
                use_multiprocessing=True if num_workers > 1 else False,
                workers=num_workers,
                callbacks=[logging, checkpoint, reduce_lr, early_stopping, loss_history]
            )
