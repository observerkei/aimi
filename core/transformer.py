import torch
from torch.utils.data import DataLoader, Dataset
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification, AdamW
import json

class QAData(Dataset):
    def __init__(self, data, tokenizer, max_length=32):
        self.data = data
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]
        encoding = self.tokenizer(item['q'], truncation=True, padding='max_length', max_length=self.max_length, return_tensors="pt")
        return {
            'input_ids': encoding['input_ids'].flatten(),
            'attention_mask': encoding['attention_mask'].flatten(),
            'labels': torch.tensor(item['label'], dtype=torch.long)
        }

def train(model, train_data, epochs, batch_size, device):
    tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")
    dataset = QAData(train_data, tokenizer)
    dataloader = DataLoader(dataset, batch_size=batch_size)

    optimizer = AdamW(model.parameters(), lr=5e-5)

    model.train()
    model.to(device)

    for epoch in range(epochs):
        for batch in dataloader:
            input_ids = batch['input_ids'].to(device)
            attention_mask = batch['attention_mask'].to(device)
            labels = batch['labels'].to(device)

            optimizer.zero_grad()

            outputs = model(input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss
            loss.backward()

            optimizer.step()

def export_model(model, file_path):
    torch.save(model.state_dict(), file_path)

def load_model(file_path):
    model = DistilBertForSequenceClassification.from_pretrained("distilbert-base-uncased")
    model.load_state_dict(torch.load(file_path))
    return model

def predict(model, query, train_data, tokenizer, device, top_k=3):
    model.eval()
    model.to(device)

    inputs = tokenizer(query, truncation=True, padding='max_length', max_length=32, return_tensors="pt")
    input_ids = inputs['input_ids'].to(device)
    attention_mask = inputs['attention_mask'].to(device)

    with torch.no_grad():
        logits = model(input_ids, attention_mask=attention_mask).logits

    probs = torch.softmax(logits, dim=-1)
    top_probs, top_labels = torch.topk(probs, top_k, dim=-1)

    result = []
    for i in range(top_k):
        result.append({
            'q': train_data[top_labels[0, i]]['q'],
            'a': train_data[top_labels[0, i]]['a'],
            'prob': top_probs[0, i].item()
        })

    return result

def transformers_predict():
    # 输入数据
    input_data =  [
        {'q': '摸摸头', 'a': '好的，请摸头', 'label': 0},
        {'q': '我想摸摸头', 'a': 'Master请摸摸头', 'label': 1},
        {'q': '我摸过你头吗?', 'a': '当然了.可以摸头', 'label': 2},
        {'q': '摸摸耳朵', 'a': '请摸耳朵', 'label': 3},
        {'q': '我摸摸耳朵', 'a': '摸摸耳朵真好', 'label': 4},
        {'q': '我能摸摸你耳朵吗?', 'a': '随时可以摸耳朵', 'label': 5}
    ]

    model = DistilBertForSequenceClassification.from_pretrained("distilbert-base-uncased", num_labels=len(input_data))
    tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    train(model, input_data, epochs=5, batch_size=2, device=device)
    #export_model(model, "trained_model.pt")

    loaded_model = model #load_model("trained_model.pt")

    # 示例1
    query = "摸头"
    print(query)
    predictions = predict(loaded_model, query, input_data, tokenizer, device, top_k=4)
    print(json.dumps(predictions, indent=2, ensure_ascii=False))

    # 示例2
    query = "摸摸耳朵"
    print(query)
    predictions = predict(loaded_model, query, input_data, tokenizer, device)
    print(json.dumps(predictions, indent=2, ensure_ascii=False))

'''
# pip install transformers

if __name__ == "__main__": 
    transformers_predict()
'''