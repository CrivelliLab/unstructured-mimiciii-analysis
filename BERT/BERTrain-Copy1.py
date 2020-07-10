import os
import torch
from torch.utils.data import Dataset
import pandas as pd
from transformers import BertTokenizer, BertForMaskedLM
from nltk.tokenize import sent_tokenize
import nltk
import time
import datetime
import pickle
import torch
from torch.utils.data import DataLoader
from torch.optim import AdamW
import random
from transformers import get_linear_schedule_with_warmup
import nltk
from nltk.translate.bleu_score import SmoothingFunction
print('here')
if torch.cuda.is_available():
    device = torch.device("cuda")

    print('There are %d GPU(s) available.' % torch.cuda.device_count())

    print('We will use the GPU:', torch.cuda.get_device_name(0))
else:
    device = torch.device('cpu')
    print("cpu")


path = "/global/cscratch1/sd/ajaybati/pickles/"

print("passed")
train_dataloader = torch.load(path+"train_dataloader.pickle")
print("pass 2")
validation_dataloader = torch.load(path+"validation_dataloader.pickle")
print("done")

tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
model = BertForMaskedLM.from_pretrained('bert-base-uncased')
torch.cuda.empty_cache()
model = model.to(device)
print("done") 

optimizer = AdamW(model.parameters(),
                  lr = 2e-5, # args.learning_rate - default is 5e-5, our notebook had 2e-5
                  eps = 1e-8 # args.adam_epsilon  - default is 1e-8.
                )

checkpoint = torch.load("/global/cscratch1/sd/ajaybati/model_ckpt.pickle")
model.load_state_dict(checkpoint['model_state_dict'])
optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
epoch = checkpoint['epoch']
total_train_loss = checkpoint['total_train_loss']
step_resume = checkpoint['step']
print(total_train_loss,step_resume)


# Number of training epochs. The BERT authors recommend between 2 and 4. 
# We chose to run for 4, but we'll see later that this may be over-fitting the
# training data.
EPOCHS = 2

# Total number of training steps is [number of batches] x [number of epochs]. 
# (Note that this is not the same as the number of training samples).
total_steps = len(train_dataloader) * EPOCHS

# Create the learning rate scheduler.
scheduler = get_linear_schedule_with_warmup(optimizer, 
                                            num_warmup_steps = 0, # Default value in run_glue.py
                                            num_training_steps = total_steps)
print("done")



def getSent_pred(prediction,real_labels):
    sentlist_real = []
    sep_list = []
    for sent2 in real_labels:
        tokenized = tokenizer.convert_ids_to_tokens(sent2)
        sep = tokenized.index('[SEP]')
        sep_list.append(sep)
        sentlist_real.append(tokenized[1:sep])
    
    
    sentlist_ids = []
    sentlist = []
    for sent in prediction:
        word_list = []
        for word in sent:
            word_list.append(torch.argmax(word))
        sentlist_ids.append(word_list)
    
    for index,sent in enumerate(sentlist_ids):
        sentlist.append(tokenizer.convert_ids_to_tokens(sent)[1:sep_list[index]])
    return sentlist,sentlist_real

def bleu(p,r):
    smoothie = SmoothingFunction().method2
    bleu_list = []
    for index in range(len(p)):
        BLEUscore = nltk.translate.bleu_score.sentence_bleu(p[index],r[index],smoothing_function=smoothie)
        bleu_list.append(BLEUscore)
    return sum(bleu_list) / len(bleu_list)

def format_time(elapsed):
    elapsed_rounded = int(round((elapsed)))
    
    return str(datetime.timedelta(seconds=elapsed_rounded))

def calc_accuracy(prediction, real_labels, mask_indices):
    score = 0
    total = 0
    for step,sent in enumerate(mask_indices):
        if list(sent).count(0)!=40:
            for mask in sent:
                if int(mask)!=0:
                    predicted_index = int(torch.argmax(prediction[step,int(mask)]))
                    actual = int(real_labels[step][int(mask)])
                    if bool(predicted_index==actual):
                        score+=1
                    total+=1
                else:
                    pass

        else:
            pass
    
    p,r = getSent_pred(predictions,real_labels)
    
    
    accuracy = score/total
    try:
        bscore = bleu(p,r)
    except:
        bscore = "Unfortunately, not possible"
    return accuracy, bscore 
print("done")
# try:
#     del total_train_loss
# except:
#     print("didn't work")
#     pass

# print(torch.cuda.memory_stats(device=device))


# ==========================================================================================

#in general remember that there are some sentence where no masks exist
seed_val = 42

random.seed(seed_val)
torch.manual_seed(seed_val)

break_factor = False
training_stats = []

# Measure the total training time for the whole run.
total_t0 = time.time()

print("starting...")
# For each epoch...
for epoch_i in range(0, EPOCHS):

    print("")
    print('======== Epoch {:} / {:} ========'.format(epoch_i + 1, EPOCHS))
    print('Training...')

    # Measure how long the training epoch takes.
    t0 = time.time()

    # Reset the total loss for this epoch.
    if epoch_i==2:
        total_train_loss = 0

    model.train()

    # For each batch of training data...
    for step, batch in enumerate(train_dataloader):
        if step>=step_resume:
            b_input_ids = batch[0].to(device)
            b_input_mask = batch[1].to(device)
            b_input_ids_real = batch[2].to(device)
            b_input_mask_ids = batch[3].to(device)

            model.zero_grad()        

            loss, predictions = model(b_input_ids, 
                                      attention_mask=b_input_mask, 
                                      masked_lm_labels=b_input_ids_real)


            total_train_loss += float(loss)

            if step % 40 == 0 and not step == 0:
                elapsed = format_time(time.time() - t0)
                print('  Batch {:>5,}  of  {:>5,}.    Elapsed: {:}.'.format(step, len(train_dataloader), elapsed))
                print("*"*50)
                print(loss)
                print("*"*50)
                acc, bscore = calc_accuracy(predictions, b_input_ids_real, b_input_mask_ids)
                print("accuracy: ", acc, "bleu: ", bscore)
                print("="*100)

            loss.backward()


            #stop exploding gradients problem.
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)

            optimizer.step()

            scheduler.step()

            if step == step_resume+40000:
                break_factor = True
                break
            
    if break_factor:
        break
    
        
        

    # Calculate the average loss over all of the batches.
    avg_train_loss = total_train_loss / len(train_dataloader)            
    
    # Measure how long this epoch took.
    training_time = format_time(time.time() - t0)

    print("")
    print("  Average training loss: {0:.2f}".format(avg_train_loss))
    print("  Training epoch took: {:}".format(training_time))
        
    # ========================================
    #               Validation
    # ========================================
    # After the completion of each training epoch, measure our performance on
    # our validation set.

    print("")
    print("Running Validation...")

    t0 = time.time()

    # Put the model in evaluation mode--the dropout layers behave differently
    # during evaluation.
    model.eval()

    # Tracking variables 
    total_eval_loss = 0
    nb_eval_steps = 0
    total_eval_accuracy = 0


    # Evaluate data for one epoch
    for step,batch in enumerate(validation_dataloader):
        
        # Unpack this training batch from our dataloader. 
        #
        # As we unpack the batch, we'll also copy each tensor to the GPU using 
        # the `to` method.
        #
        # `batch` contains three pytorch tensors:
        #   [0]: input ids 
        #   [1]: attention masks
        #   [2]: real ids
        #   [3]: mask ids for comparison
        b_input_ids = batch[0].to(device)
        b_input_mask = batch[1].to(device)
        b_input_ids_real = batch[2].to(device)
        b_input_mask_ids = batch[3].to(device)
        
        
        with torch.no_grad():        

            (loss, logits) = model(b_input_ids, 
                                   attention_mask=b_input_mask, 
                                   masked_lm_labels=b_input_ids)
            
        # Accumulate the validation loss.
        total_eval_loss += loss.item()
        accuracy, bleuscore = calc_accuracy(logits, b_input_ids_real, b_input_mask_ids)
        total_eval_accuracy += accuracy

    # Report the final accuracy for this validation run.
    avg_val_accuracy = total_eval_accuracy / len(validation_dataloader)
    print("  Accuracy: {0:.2f}".format(avg_val_accuracy))
    
    
    avg_val_loss = total_eval_loss / len(validation_dataloader)
    
    validation_time = format_time(time.time() - t0)
    
    print("  Validation Loss: {0:.2f}".format(avg_val_loss))
    print("  Validation took: {:}".format(validation_time))

    training_stats.append(
        {
            'epoch': epoch_i + 1,
            'Avg Accuracy': avg_cal_accuracy,
            'Latest Bleu Score': bleuscore,
            'Training Loss': avg_train_loss,
            'Valid. Loss': avg_val_loss,
            'Training Time': training_time,
            'Validation Time': validation_time
        }
    )

print("")
print("Training complete!")

print("Total training took {:} (h:mm:ss)".format(format_time(time.time()-total_t0)))

# model_to_save = model.module if hasattr(model, 'module') else model  # Take care of distributed/parallel training
# model_to_save.save_pretrained(path)
# tokenizer.save_pretrained(path)

torch.save({
            'epoch': epoch_i,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'loss': loss,
            'total_train_loss': total_train_loss,
            'step': step
            }, "/global/cscratch1/sd/ajaybati/model_ckpt.pickle")


# with open(path+'training_stats.pickle', 'wb') as f:
#     pickle.dump(training_stats, f)
