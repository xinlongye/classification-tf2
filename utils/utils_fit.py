import tensorflow as tf
from tqdm import tqdm

# 防止bug
def get_train_step_fn():
    # @tf.function
    def train_step(batch_images, batch_labels, net, optimizer):
        with tf.GradientTape() as tape:
            predict = net([batch_images], training=True)
            loss_value = tf.reduce_sum(tf.losses.categorical_crossentropy(batch_labels, predict))

        grads = tape.gradient(loss_value, net.trainable_variables)
        optimizer.apply_gradients(zip(grads, net.trainable_variables))
        acc = tf.reduce_mean(tf.cast(tf.equal(tf.argmax(predict, axis=-1), tf.argmax(batch_labels, axis=-1)), tf.float32))
        return loss_value, acc
    return train_step

@tf.function
def val_step(batch_images, batch_labels, net, optimizer):
    predict = net(batch_images)
    loss_value = tf.reduce_sum(tf.losses.categorical_crossentropy(batch_labels, predict))
    return loss_value

def fit_one_epoch(net, loss_history, optimizer, epoch, epoch_step, epoch_step_val, gen, gen_val, Epoch):
    train_step  = get_train_step_fn()

    total_loss  = 0
    total_acc   = 0
    val_loss    = 0
    print('Start Train')
    with tqdm(total=epoch_step,desc=f'Epoch {epoch + 1}/{Epoch}',postfix=dict,mininterval=0.3) as pbar:
        for iteration, batch in enumerate(gen):
            if iteration>=epoch_step:
                break
            batch = [tf.convert_to_tensor(part) for part in batch]
            batch_images, batch_labels = batch

            loss_value, acc= train_step(batch_images, batch_labels, net, optimizer)
            total_loss  += loss_value
            total_acc   += acc

            pbar.set_postfix(**{'total_loss'    : float(total_loss) / (iteration + 1), 
                                'acc'           : float(total_acc) / (iteration + 1), 
                                'lr'            : optimizer._decayed_lr(tf.float32).numpy()})
            pbar.update(1)
    print('Finish Train')

    print('Start Validation')
    with tqdm(total=epoch_step_val, desc=f'Epoch {epoch + 1}/{Epoch}',postfix=dict,mininterval=0.3) as pbar:
        for iteration, batch in enumerate(gen_val):
            if iteration>=epoch_step_val:
                break
            batch = [tf.convert_to_tensor(part) for part in batch]
            batch_images, batch_labels = batch

            loss_value  = val_step(batch_images, batch_labels, net, optimizer)
            val_loss    += loss_value

            pbar.set_postfix(**{'val_loss': float(val_loss)/ (iteration + 1)})
            pbar.update(1)
    print('Finish Validation')

    logs = {'loss': total_loss.numpy() / epoch_step, 'val_loss': val_loss.numpy() / epoch_step_val}
    loss_history.on_epoch_end([], logs)
    print('Epoch:'+ str(epoch+1) + '/' + str(Epoch))
    print('Total Loss: %.3f || Val Loss: %.3f ' % (total_loss / epoch_step, val_loss / epoch_step_val))
    net.save_weights('logs/ep%03d-loss%.3f-val_loss%.3f.h5' % (epoch + 1, total_loss / epoch_step, val_loss / epoch_step_val))
